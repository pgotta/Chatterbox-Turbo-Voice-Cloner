from __future__ import annotations

import os
import csv
import html
import json
import queue
import random
import shutil
import subprocess
import sys
import threading
import time
import traceback
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import numpy as np
import sounddevice as sd
import soundfile as sf
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import torch
import torchaudio as ta
from chatterbox.tts_turbo import ChatterboxTurboTTS


BASE = Path(__file__).resolve().parent
OUT = BASE / "output"
LOG = BASE / "logs"
REC = BASE / "recordings"
for p in (OUT, LOG, REC):
    p.mkdir(exist_ok=True)

# Current Chatterbox Turbo defaults from the upstream Turbo implementation/demo.
DEFAULTS = {
    "temperature": 0.8,
    "top_p": 0.95,
    "top_k": 1000,
    "repetition_penalty": 1.2,
    "norm_loudness": True,
}

EVENT_TAGS = [
    "[clear throat]", "[sigh]", "[shush]", "[cough]", "[groan]",
    "[sniff]", "[gasp]", "[chuckle]", "[laugh]"
]

SUPPORTED_AUDIO_EXTS = {".wav", ".flac", ".mp3", ".ogg", ".m4a"}

# Human-friendly Kokoro descriptors. These are community-maintained descriptors,
# not official personality labels from the Kokoro model authors. The audition page
# calls that out explicitly so they are useful hints rather than treated as ground truth.
KOKORO_VOICE_INFO = {
    # American English
    "af_alloy":   {"gender": "Female", "style": "Clear, professional"},
    "af_aoede":   {"gender": "Female", "style": "Smooth, melodic"},
    "af_bella":   {"gender": "Female", "style": "Warm, friendly / expressive"},
    "af_heart":   {"gender": "Female", "style": "Warm, natural"},
    "af_jessica": {"gender": "Female", "style": "Natural, engaging / energetic"},
    "af_kore":    {"gender": "Female", "style": "Bright, energetic"},
    "af_nicole":  {"gender": "Female", "style": "Professional, articulate / friendly"},
    "af_nova":    {"gender": "Female", "style": "Modern, dynamic / clear"},
    "af_river":   {"gender": "Female", "style": "Soft, flowing / calm"},
    "af_sarah":   {"gender": "Female", "style": "Casual, approachable / conversational"},
    "af_sky":     {"gender": "Female", "style": "Light, airy / neutral"},
    "am_adam":    {"gender": "Male", "style": "Deep / strong, confident"},
    "am_echo":    {"gender": "Male", "style": "Resonant, clear / neutral"},
    "am_eric":    {"gender": "Male", "style": "Professional, authoritative"},
    "am_fenrir":  {"gender": "Male", "style": "Deep, powerful / distinctive"},
    "am_liam":    {"gender": "Male", "style": "Friendly, conversational"},
    "am_michael": {"gender": "Male", "style": "Warm, trustworthy / clear"},
    "am_onyx":    {"gender": "Male", "style": "Rich, sophisticated"},
    "am_puck":    {"gender": "Male", "style": "Playful, energetic / expressive"},
    "am_santa":   {"gender": "Male", "style": "Warm"},

    # British English
    "bf_alice":    {"gender": "Female", "style": "Refined, elegant / crisp"},
    "bf_emma":     {"gender": "Female", "style": "Warm, professional / clear"},
    "bf_isabella": {"gender": "Female", "style": "Sophisticated, clear / warm"},
    "bf_lily":     {"gender": "Female", "style": "Sweet, gentle / soft"},
    "bm_daniel":   {"gender": "Male", "style": "Polished, professional / calm"},
    "bm_fable":    {"gender": "Male", "style": "Storytelling, engaging / expressive"},
    "bm_george":   {"gender": "Male", "style": "Authoritative, classic British"},
    "bm_lewis":    {"gender": "Male", "style": "Smooth, modern British"},

    # Spanish
    "ef_dora":  {"gender": "Female", "style": "Clear, youthful"},
    "em_alex":  {"gender": "Male", "style": "Youthful, neutral"},
    "em_santa": {"gender": "Male", "style": "Older, warm"},

    # French
    "ff_siwis": {"gender": "Female", "style": "French voice"},

    # Hindi
    "hf_alpha": {"gender": "Female", "style": "Clear, precise"},
    "hf_beta":  {"gender": "Female", "style": "Softer tone"},
    "hm_omega": {"gender": "Male", "style": "Deep"},
    "hm_psi":   {"gender": "Male", "style": "Calm"},

    # Italian
    "if_sara":   {"gender": "Female", "style": "Expressive"},
    "im_nicola": {"gender": "Male", "style": "Warm"},

    # Japanese
    "jf_alpha":      {"gender": "Female", "style": "Clear"},
    "jf_gongitsune": {"gender": "Female", "style": "Softer tone"},
    "jf_nezumi":     {"gender": "Female", "style": "Gentle"},
    "jf_tebukuro":   {"gender": "Female", "style": "Warm"},
    "jm_kumo":       {"gender": "Male", "style": ""},

    # Brazilian Portuguese - factual gender only where a consistent style descriptor
    # was not available across the reviewed community catalogs.
    "pf_dora":  {"gender": "Female", "style": ""},
    "pm_alex":  {"gender": "Male", "style": ""},
    "pm_santa": {"gender": "Male", "style": ""},

    # Mandarin Chinese
    "zf_xiaobei":  {"gender": "Female", "style": "Young, energetic"},
    "zf_xiaoni":   {"gender": "Female", "style": "Clear, friendly"},
    "zf_xiaoxiao": {"gender": "Female", "style": "Soft, gentle"},
    "zf_xiaoyi":   {"gender": "Female", "style": "Professional, articulate"},
    "zm_yunjian":  {"gender": "Male", "style": "Strong, confident"},
    "zm_yunxi":    {"gender": "Male", "style": "Warm, professional"},
    "zm_yunxia":   {"gender": "Male", "style": "Calm, steady"},
    "zm_yunyang":  {"gender": "Male", "style": "Resonant, deep"},
}

KOKORO_STYLE_NOTE = (
    "Style words are community-maintained listening descriptors, not official Kokoro "
    "personality labels. Treat them as audition hints and trust your ears."
)


@dataclass(frozen=True)
class VoiceRef:
    path: Path
    display_name: str
    voice_id: str = ""
    group_path: str = "Uncategorized"
    language_label: str = "Uncategorized"
    gender: str = ""
    style: str = ""


def normalize_path_key(path: Path) -> str:
    """Case-insensitive normalized key on Windows, harmless elsewhere."""
    try:
        value = str(path.resolve())
    except Exception:
        value = str(path.absolute())
    return os.path.normcase(value)


def humanize_group(value: str) -> str:
    text = str(value or "").replace("\\", "/").strip("/")
    if not text or text == ".":
        return "Uncategorized"
    return " / ".join(part.replace("_", " ") for part in text.split("/"))


def parse_voice_stem(stem: str):
    """Understand package names like Adam__am_adam and raw IDs like am_adam."""
    if "__" in stem:
        name, voice_id = stem.split("__", 1)
        return name.replace("_", " ").strip() or "Voice", voice_id.strip()

    bits = stem.split("_", 1)
    if len(bits) == 2 and len(bits[0]) == 2 and bits[0].isalpha():
        voice_id = stem
        name = bits[1].replace("_", " ").strip().title()
        return name or stem, voice_id

    return stem.replace("_", " ").strip() or "Voice", ""


def safe_group_path(group_path: str) -> Path:
    raw = str(group_path or "Uncategorized").replace("\\", "/").strip("/")
    parts = [safe_name(part) for part in raw.split("/") if part and part != "."]
    return Path(*parts) if parts else Path("Uncategorized")

HELP = {
    "temperature":
        "Temperature controls randomness in speech-token sampling.\n\n"
        "Lower values are more predictable and consistent. Higher values create "
        "more variation, but can also increase odd pronunciations, substitutions "
        "or artifacts.\n\nTurbo default: 0.8.",
    "top_p":
        "Top P (nucleus sampling) limits sampling to the most likely tokens whose "
        "combined probability reaches this threshold.\n\nLower values are more "
        "focused/predictable. Higher values allow more variety.\n\nTurbo default: 0.95.",
    "top_k":
        "Top K limits each sampling step to the K most likely speech tokens.\n\n"
        "Lower values constrain generation more strongly. Higher values allow "
        "more possibilities.\n\nTurbo default: 1000.",
    "repetition_penalty":
        "Repetition Penalty discourages recently generated tokens from repeating.\n\n"
        "Higher values can reduce loops/stuttering, but pushing it too far may "
        "hurt natural speech or word accuracy.\n\nTurbo default: 1.2.",
    "norm_loudness":
        "Normalize Loudness adjusts the reference voice level before Chatterbox "
        "extracts its conditioning features. It helps quiet/loud prompts behave "
        "more consistently.\n\nTurbo default: On.",
    "exaggeration":
        "Important: current Chatterbox Turbo ignores exaggeration.\n\n"
        "Emotion exaggeration is supported by the original Chatterbox and "
        "multilingual models, not the current Turbo inference path. Resemble AI "
        "says Turbo removed it because naturalness was worse in the smaller Turbo model.",
    "cfg_weight":
        "Important: current Chatterbox Turbo ignores CFG weight.\n\n"
        "Classifier-Free Guidance is supported by the original/multilingual model "
        "families. Resemble AI says Turbo removed CFG to avoid roughly doubling "
        "generation compute.",
    "min_p":
        "Important: the current Turbo implementation accepts a min_p argument but "
        "explicitly warns that it is unsupported and ignores it. The official "
        "Turbo demo leaves it at 0.0.",
    "speed":
        "Chatterbox Turbo does not currently expose a direct speaking-speed parameter. "
        "Pacing mostly comes from the reference voice, punctuation, wording and the "
        "model's sampling behavior.",
    "tags":
        "Turbo supports paralinguistic event tags embedded directly in the text. "
        "Use the buttons to insert a tag at the current cursor position.\n\n"
        "Official demo tags include clear throat, sigh, shush, cough, groan, sniff, "
        "gasp, chuckle and laugh."
}


def gpucheck():
    """Verify that a CUDA-capable NVIDIA GPU is available and usable."""
    if not torch.cuda.is_available():
        raise RuntimeError(
            "CUDA unavailable; this build requires a CUDA-capable NVIDIA GPU. "
            "CPU fallback is disabled."
        )
    name = torch.cuda.get_device_name(0)
    x = torch.randn((16, 16), device="cuda")
    _ = x @ x
    torch.cuda.synchronize()
    return name


def seed_all(seed: int):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def safe_name(s: str):
    result = "".join(c if c.isalnum() or c in "-_ " else "_" for c in s).strip()
    return result.replace(" ", "_") or "voice"


class App:
    def __init__(self, root):
        self.root = root
        root.title("Chatterbox Turbo Voice Cloner - Audition Selection")
        root.geometry("1040x920")
        root.minsize(880, 760)

        self.q = queue.Queue()
        self.model = None
        self.busy = False
        self.refs: list[VoiceRef] = []
        self.advanced_visible = False

        # microphone state
        self.mic_stream = None
        self.mic_chunks = []
        self.mic_samplerate = 48000
        self.mic_channels = 1
        self.recording = False
        self.record_started = None

        try:
            self.gpu = gpucheck()
        except Exception as e:
            messagebox.showerror("GPU error", str(e))
            root.destroy()
            return

        self.build()
        self.log(f"GPU verified: {self.gpu} | CUDA {torch.version.cuda} | PyTorch {torch.__version__}")
        root.after(100, self.pump)
        root.after(250, self.refresh_record_timer)

    def build(self):
        # Scrollable window so advanced controls fit on smaller laptop displays.
        canvas = tk.Canvas(self.root, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.root, orient="vertical", command=canvas.yview)
        self.main = ttk.Frame(canvas, padding=14)
        self.main.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=self.main, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        f = self.main

        ttk.Label(
            f,
            text="Chatterbox Turbo Voice Cloner",
            font=("Segoe UI", 17, "bold")
        ).pack(anchor="w")
        ttk.Label(
            f,
            text=f"{self.gpu} | GPU-only | Recursive voices + selectable audition takes"
        ).pack(anchor="w", pady=(2, 12))

        refs = ttk.LabelFrame(f, text="1. Reference voices", padding=10)
        refs.pack(fill="x")

        refs_top = ttk.Frame(refs)
        refs_top.pack(fill="both", expand=True)

        left = ttk.Frame(refs_top)
        left.pack(side="left", fill="both", expand=True)

        self.listbox = tk.Listbox(left, height=8, selectmode=tk.EXTENDED)
        self.listbox.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(left, orient="vertical", command=self.listbox.yview)
        sb.pack(side="right", fill="y")
        self.listbox.configure(yscrollcommand=sb.set)

        btns = ttk.Frame(refs_top)
        btns.pack(side="right", fill="y", padx=(10, 0))
        ttk.Button(btns, text="Add audio files...", command=self.add_refs).pack(fill="x", pady=(0, 5))
        ttk.Button(btns, text="Add voice folder...", command=self.add_voice_folder).pack(fill="x", pady=5)
        ttk.Button(btns, text="Remove selected", command=self.remove_refs).pack(fill="x", pady=5)
        ttk.Button(btns, text="Clear list", command=self.clear_refs).pack(fill="x", pady=5)

        self.ref_summary = tk.StringVar(value="No references loaded")
        ttk.Label(refs, textvariable=self.ref_summary).pack(fill="x", anchor="w", pady=(7, 0))

        mic = ttk.LabelFrame(f, text="2. Record your own reference voice", padding=10)
        mic.pack(fill="x", pady=10)

        mrow = ttk.Frame(mic)
        mrow.pack(fill="x")
        ttk.Label(mrow, text="Microphone:").pack(side="left")
        self.mic_name = tk.StringVar()
        self.mic_combo = ttk.Combobox(mrow, textvariable=self.mic_name, state="readonly", width=48)
        self.mic_combo.pack(side="left", padx=(6, 8))
        ttk.Button(mrow, text="Refresh", command=self.load_mics).pack(side="left", padx=(0, 12))
        self.rec_btn = ttk.Button(mrow, text="Start recording", command=self.toggle_record)
        self.rec_btn.pack(side="left")
        self.rec_time = tk.StringVar(value="00:00")
        ttk.Label(mrow, textvariable=self.rec_time, font=("Segoe UI", 10, "bold")).pack(side="left", padx=10)

        ttk.Label(
            mic,
            text="Record about 10-30 seconds in a quiet room. Stopping automatically saves and adds the WAV to the batch."
        ).pack(anchor="w", pady=(6, 0))

        textframe = ttk.LabelFrame(f, text="3. Text to generate", padding=10)
        textframe.pack(fill="x")

        self.txt = tk.Text(textframe, height=7, wrap="word")
        self.txt.pack(fill="x")
        self.txt.insert(
            "1.0",
            "This is what the selected voice sounds like. Listen to the tone, pacing and overall "
            "character of the speaker. Sounds pretty natural, doesn't it? A good voice should feel "
            "clear, comfortable and easy to listen to. Let's hear what it can really do!"
        )
        self.txt.bind("<KeyRelease>", lambda e: self.update_char_count())

        tagrow = ttk.Frame(textframe)
        tagrow.pack(fill="x", pady=(7, 0))
        ttk.Label(tagrow, text="Event tags:").pack(side="left")
        for tag in EVENT_TAGS:
            ttk.Button(
                tagrow,
                text=tag,
                width=max(7, len(tag)),
                command=lambda t=tag: self.insert_tag(t)
            ).pack(side="left", padx=2)
        ttk.Button(tagrow, text="?", width=3, command=lambda: self.show_help("tags")).pack(side="left", padx=(5, 0))

        self.char_count = tk.StringVar()
        ttk.Label(textframe, textvariable=self.char_count).pack(anchor="e", pady=(4, 0))
        self.update_char_count()

        # Collapsible advanced section, closed by default.
        self.advanced_toggle = ttk.Button(
            f,
            text="▶ Advanced Chatterbox Turbo settings",
            command=self.toggle_advanced
        )
        self.advanced_toggle.pack(fill="x", pady=(10, 0))

        self.advanced = ttk.Frame(f, padding=(10, 8, 10, 8))
        self.build_advanced(self.advanced)
        # Intentionally not packed: collapsed by default.

        opts = ttk.Frame(f)
        opts.pack(fill="x", pady=10)

        ttk.Label(opts, text="Takes per voice:").pack(side="left")
        self.takes = tk.StringVar(value="3")
        ttk.Spinbox(opts, from_=1, to=10, width=5, textvariable=self.takes).pack(side="left", padx=(5, 15))

        ttk.Label(opts, text="Starting seed:").pack(side="left")
        self.seed = tk.StringVar(value="4200")
        ttk.Entry(opts, width=9, textvariable=self.seed).pack(side="left", padx=(5, 15))

        self.go = ttk.Button(opts, text="Generate batch", command=self.start_batch)
        self.go.pack(side="left")
        ttk.Button(opts, text="Open output", command=lambda: os.startfile(OUT)).pack(side="right")
        ttk.Button(
            opts, text="Rebuild existing audition...", command=self.rebuild_existing_audition
        ).pack(side="right", padx=(0, 7))

        self.status = tk.StringVar(value="Ready")
        ttk.Label(f, textvariable=self.status, font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(8, 4))

        self.pb = ttk.Progressbar(f, mode="determinate")
        self.pb.pack(fill="x")

        ttk.Label(f, text="Activity").pack(anchor="w", pady=(10, 3))
        self.lb = tk.Text(f, height=12, state="disabled", wrap="word")
        self.lb.pack(fill="both", expand=True)

        self.load_mics()

    def build_advanced(self, frame):
        box = ttk.LabelFrame(frame, text="Advanced Chatterbox Turbo settings", padding=10)
        box.pack(fill="x")

        self.temperature = tk.DoubleVar(value=DEFAULTS["temperature"])
        self.top_p = tk.DoubleVar(value=DEFAULTS["top_p"])
        self.top_k = tk.IntVar(value=DEFAULTS["top_k"])
        self.repetition_penalty = tk.DoubleVar(value=DEFAULTS["repetition_penalty"])
        self.norm_loudness = tk.BooleanVar(value=DEFAULTS["norm_loudness"])

        def slider_row(row, label, var, frm, to, resolution, help_key, default_text):
            ttk.Label(box, text=label, width=22).grid(row=row, column=0, sticky="w", pady=4)
            scale = tk.Scale(
                box, from_=frm, to=to, resolution=resolution, orient="horizontal",
                variable=var, length=420, showvalue=True
            )
            scale.grid(row=row, column=1, sticky="ew", padx=(5, 8))
            ttk.Label(box, text=f"Default {default_text}", width=15).grid(row=row, column=2, sticky="w")
            ttk.Button(box, text="?", width=3, command=lambda k=help_key: self.show_help(k)).grid(
                row=row, column=3, padx=(4, 0)
            )

        slider_row(0, "Temperature", self.temperature, 0.05, 2.0, 0.05, "temperature", "0.8")
        slider_row(1, "Top P", self.top_p, 0.0, 1.0, 0.01, "top_p", "0.95")
        slider_row(2, "Top K", self.top_k, 1, 1000, 1, "top_k", "1000")
        slider_row(3, "Repetition penalty", self.repetition_penalty, 1.0, 2.0, 0.05, "repetition_penalty", "1.2")

        ttk.Label(box, text="Normalize loudness", width=22).grid(row=4, column=0, sticky="w", pady=6)
        ttk.Checkbutton(box, variable=self.norm_loudness, text="Match reference prompt volume").grid(
            row=4, column=1, sticky="w", padx=(5, 8)
        )
        ttk.Label(box, text="Default On", width=15).grid(row=4, column=2, sticky="w")
        ttk.Button(box, text="?", width=3, command=lambda: self.show_help("norm_loudness")).grid(
            row=4, column=3, padx=(4, 0)
        )

        ttk.Separator(box).grid(row=5, column=0, columnspan=4, sticky="ew", pady=8)

        # Informational rows for controls users often see documented for other Chatterbox models.
        ttk.Label(box, text="Exaggeration", width=22).grid(row=6, column=0, sticky="w", pady=4)
        ttk.Label(box, text="Not supported by current Turbo (ignored)", foreground="#777777").grid(
            row=6, column=1, columnspan=2, sticky="w", padx=(5, 8)
        )
        ttk.Button(box, text="?", width=3, command=lambda: self.show_help("exaggeration")).grid(row=6, column=3)

        ttk.Label(box, text="CFG weight", width=22).grid(row=7, column=0, sticky="w", pady=4)
        ttk.Label(box, text="Not supported by current Turbo (ignored)", foreground="#777777").grid(
            row=7, column=1, columnspan=2, sticky="w", padx=(5, 8)
        )
        ttk.Button(box, text="?", width=3, command=lambda: self.show_help("cfg_weight")).grid(row=7, column=3)

        ttk.Label(box, text="Min P", width=22).grid(row=8, column=0, sticky="w", pady=4)
        ttk.Label(box, text="Accepted by API but ignored by current Turbo", foreground="#777777").grid(
            row=8, column=1, columnspan=2, sticky="w", padx=(5, 8)
        )
        ttk.Button(box, text="?", width=3, command=lambda: self.show_help("min_p")).grid(row=8, column=3)

        ttk.Label(box, text="Speaking speed", width=22).grid(row=9, column=0, sticky="w", pady=4)
        ttk.Label(box, text="No direct Turbo speed parameter", foreground="#777777").grid(
            row=9, column=1, columnspan=2, sticky="w", padx=(5, 8)
        )
        ttk.Button(box, text="?", width=3, command=lambda: self.show_help("speed")).grid(row=9, column=3)

        ttk.Separator(box).grid(row=10, column=0, columnspan=4, sticky="ew", pady=8)
        ttk.Button(box, text="Reset all to Turbo defaults", command=self.reset_defaults).grid(
            row=11, column=0, columnspan=2, sticky="w", pady=(2, 0)
        )

        box.columnconfigure(1, weight=1)

    def toggle_advanced(self):
        if self.advanced_visible:
            self.advanced.pack_forget()
            self.advanced_toggle.configure(text="▶ Advanced Chatterbox Turbo settings")
            self.advanced_visible = False
        else:
            self.advanced.pack(fill="x", pady=(0, 5), after=self.advanced_toggle)
            self.advanced_toggle.configure(text="▼ Advanced Chatterbox Turbo settings")
            self.advanced_visible = True

    def show_help(self, key):
        messagebox.showinfo("Chatterbox Turbo setting", HELP[key])

    def reset_defaults(self):
        self.temperature.set(DEFAULTS["temperature"])
        self.top_p.set(DEFAULTS["top_p"])
        self.top_k.set(DEFAULTS["top_k"])
        self.repetition_penalty.set(DEFAULTS["repetition_penalty"])
        self.norm_loudness.set(DEFAULTS["norm_loudness"])
        self.log("Advanced Turbo settings reset to official defaults.")

    def insert_tag(self, tag):
        try:
            index = self.txt.index(tk.INSERT)
            before = self.txt.get("1.0", index)
            after = self.txt.get(index, "end-1c")
            prefix = "" if not before or before.endswith((" ", "\n")) else " "
            suffix = "" if not after or after.startswith((" ", "\n")) else " "
            self.txt.insert(index, prefix + tag + suffix)
            self.update_char_count()
        except Exception:
            self.txt.insert("end", " " + tag)
            self.update_char_count()

    def update_char_count(self):
        n = len(self.txt.get("1.0", "end-1c"))
        suffix = "  (official demo recommends ≤300 chars per generation)" if n > 300 else ""
        self.char_count.set(f"{n} characters{suffix}")

    # ---------- reference list ----------
    def update_ref_list(self):
        self.listbox.delete(0, tk.END)
        for ref in self.refs:
            ident = f" ({ref.voice_id})" if ref.voice_id else ""
            self.listbox.insert(
                tk.END,
                f"{ref.language_label} | {ref.display_name}{ident} | {ref.path.name}"
            )

        if not self.refs:
            self.ref_summary.set("No references loaded")
            return

        counts = Counter(ref.language_label for ref in self.refs)
        groups = ", ".join(f"{name}: {count}" for name, count in sorted(counts.items()))
        self.ref_summary.set(f"{len(self.refs)} reference(s) across {len(counts)} group(s) | {groups}")

    def _metadata_for_folder(self, root: Path):
        """Load optional voices.json metadata from a voice package root."""
        candidates = [
            root / "metadata" / "voices.json",
            root / "voices.json",
        ]
        # Also allow one nested metadata file in a package wrapper folder.
        if not any(p.exists() for p in candidates):
            try:
                nested = list(root.glob("*/metadata/voices.json"))
                if len(nested) == 1:
                    candidates.append(nested[0])
            except Exception:
                pass

        by_path = {}
        by_name = {}
        source = None
        for candidate in candidates:
            if not candidate.exists():
                continue
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
                voices = data.get("voices", []) if isinstance(data, dict) else data
                if not isinstance(voices, list):
                    continue

                metadata_root = candidate.parent.parent if candidate.parent.name.lower() == "metadata" else candidate.parent
                for record in voices:
                    if not isinstance(record, dict):
                        continue
                    rel = record.get("wav_path") or record.get("file") or record.get("path")
                    if rel:
                        try:
                            expected = metadata_root / Path(str(rel).replace("\\", "/"))
                            by_path[normalize_path_key(expected)] = record
                            by_name[Path(str(rel)).name.lower()] = record
                        except Exception:
                            pass
                    voice_id = str(record.get("voice_id") or record.get("id") or "").strip()
                    if voice_id:
                        by_name[f"{voice_id}.wav".lower()] = record
                source = candidate
                break
            except Exception as e:
                self.log(f"Could not read voice metadata {candidate}: {e}")

        return by_path, by_name, source

    def _make_voice_ref(self, path: Path, root: Path | None = None, metadata=None, recorded=False):
        path = Path(path)
        display_name, voice_id = parse_voice_stem(path.stem)

        group_path = "Recorded_Microphone" if recorded else ""
        language_label = "Recorded Microphone" if recorded else ""
        gender = ""
        style = ""

        if root is not None:
            try:
                rel = path.relative_to(root)
                parent = rel.parent.as_posix()
                group_path = parent if parent not in ("", ".") else "Uncategorized"
            except Exception:
                group_path = path.parent.name or "Uncategorized"
        elif not recorded:
            group_path = path.parent.name or "Manual_References"

        if metadata:
            display_name = str(metadata.get("display_name") or display_name).strip() or display_name
            voice_id = str(metadata.get("voice_id") or metadata.get("id") or voice_id).strip()
            gender = str(metadata.get("gender") or "").strip().title()
            style = str(metadata.get("style") or metadata.get("voice_style") or "").strip()
            language_label = str(
                metadata.get("accent_or_variant")
                or metadata.get("language_variant")
                or metadata.get("language")
                or ""
            ).strip()
            rel = metadata.get("wav_path") or metadata.get("file") or metadata.get("path")
            if rel:
                try:
                    parent = Path(str(rel).replace("\\", "/")).parent.as_posix()
                    if parent not in ("", "."):
                        group_path = parent
                except Exception:
                    pass

        if not language_label:
            language_label = humanize_group(group_path)

        kokoro_info = KOKORO_VOICE_INFO.get(voice_id.lower()) if voice_id else None
        if kokoro_info:
            gender = kokoro_info.get("gender") or gender
            style = kokoro_info.get("style") or style

        return VoiceRef(
            path=path,
            display_name=display_name,
            voice_id=voice_id,
            group_path=group_path or "Uncategorized",
            language_label=language_label or "Uncategorized",
            gender=gender,
            style=style,
        )

    def _append_ref(self, ref: VoiceRef) -> bool:
        key = normalize_path_key(ref.path)
        if any(normalize_path_key(existing.path) == key for existing in self.refs):
            return False
        self.refs.append(ref)
        return True

    def add_refs(self):
        files = filedialog.askopenfilenames(
            title="Choose one or more reference voices",
            filetypes=[
                ("Audio files", "*.wav *.flac *.mp3 *.ogg *.m4a"),
                ("All files", "*.*")
            ]
        )
        added = 0
        for item in files:
            p = Path(item)
            if p.suffix.lower() not in SUPPORTED_AUDIO_EXTS:
                continue
            if self._append_ref(self._make_voice_ref(p)):
                added += 1
        self.update_ref_list()
        if files:
            self.log(f"Added {added} reference file(s). Total: {len(self.refs)}")

    def add_voice_folder(self):
        selected = filedialog.askdirectory(title="Choose the top-level voices folder")
        if not selected:
            return

        root = Path(selected)
        by_path, by_name, metadata_source = self._metadata_for_folder(root)

        skip_dirs = {"output", "logs", "recordings", ".venv", "venv", "__pycache__"}
        discovered = []
        try:
            for p in root.rglob("*"):
                if not p.is_file() or p.suffix.lower() not in SUPPORTED_AUDIO_EXTS:
                    continue
                try:
                    rel_parts = {part.lower() for part in p.relative_to(root).parts[:-1]}
                    if rel_parts & skip_dirs:
                        continue
                except Exception:
                    pass
                discovered.append(p)
        except Exception as e:
            messagebox.showerror("Voice folder", f"Could not scan the folder:\n{e}")
            return

        discovered.sort(key=lambda p: str(p.relative_to(root)).lower())
        added = 0
        for p in discovered:
            record = by_path.get(normalize_path_key(p)) or by_name.get(p.name.lower())
            ref = self._make_voice_ref(p, root=root, metadata=record)
            if self._append_ref(ref):
                added += 1

        self.update_ref_list()

        if not discovered:
            messagebox.showinfo("Voice folder", "No supported audio files were found in that folder or its subfolders.")
            return

        counts = Counter(ref.language_label for ref in self.refs if normalize_path_key(ref.path).startswith(normalize_path_key(root)))
        breakdown = "; ".join(f"{name}: {count}" for name, count in sorted(counts.items()))
        metadata_note = f" Metadata: {metadata_source.name}." if metadata_source else ""
        self.log(
            f"Recursive voice-folder scan: {root} | found {len(discovered)} audio file(s), "
            f"added {added}. {breakdown}.{metadata_note}"
        )
        self.q.put(("status", f"Loaded {added} new voice(s) from {root.name}"))

    def remove_refs(self):
        indices = list(self.listbox.curselection())
        for idx in reversed(indices):
            del self.refs[idx]
        self.update_ref_list()

    def clear_refs(self):
        self.refs.clear()
        self.update_ref_list()

    def reference_duration(self, path: Path):
        """Fast preflight duration check; returns None when a codec cannot be probed."""
        try:
            info = sf.info(str(path))
            if info.samplerate:
                return float(info.frames) / float(info.samplerate)
        except Exception:
            pass
        try:
            info = ta.info(str(path))
            if info.sample_rate:
                return float(info.num_frames) / float(info.sample_rate)
        except Exception:
            pass
        return None

    # ---------- microphone ----------
    def input_devices(self):
        result = []
        for idx, d in enumerate(sd.query_devices()):
            if int(d["max_input_channels"]) > 0:
                result.append((idx, d["name"]))
        return result

    def load_mics(self):
        try:
            self.mics = self.input_devices()
            values = [f"{idx}: {name}" for idx, name in self.mics]
            self.mic_combo["values"] = values
            if values and not self.mic_name.get():
                default_in = sd.default.device[0]
                chosen = 0
                for i, (idx, _) in enumerate(self.mics):
                    if idx == default_in:
                        chosen = i
                        break
                self.mic_combo.current(chosen)
        except Exception as e:
            self.log(f"Microphone enumeration error: {e}")

    def selected_mic_index(self):
        value = self.mic_name.get()
        if not value:
            return None
        try:
            return int(value.split(":", 1)[0])
        except Exception:
            return None

    def audio_callback(self, indata, frames, time_info, status):
        if status:
            self.log(f"Microphone status: {status}")
        self.mic_chunks.append(indata.copy())

    def toggle_record(self):
        if self.recording:
            self.stop_record()
        else:
            self.start_record()

    def start_record(self):
        if self.busy:
            messagebox.showinfo("Busy", "Wait for the current generation batch to finish.")
            return
        device = self.selected_mic_index()
        if device is None:
            messagebox.showinfo("Microphone", "Select a microphone first.")
            return

        try:
            info = sd.query_devices(device, "input")
            self.mic_samplerate = int(info["default_samplerate"] or 48000)
            self.mic_chunks = []
            self.mic_stream = sd.InputStream(
                device=device,
                samplerate=self.mic_samplerate,
                channels=1,
                dtype="float32",
                callback=self.audio_callback
            )
            self.mic_stream.start()
            self.recording = True
            self.record_started = time.time()
            self.rec_btn.configure(text="Stop recording")
            self.log(f"Recording started: {info['name']} @ {self.mic_samplerate} Hz")
        except Exception as e:
            messagebox.showerror("Microphone error", str(e))
            self.log(f"Microphone start failed: {e}")

    def stop_record(self):
        if not self.recording:
            return
        try:
            if self.mic_stream:
                self.mic_stream.stop()
                self.mic_stream.close()
        finally:
            self.mic_stream = None
            self.recording = False
            self.rec_btn.configure(text="Start recording")

        if not self.mic_chunks:
            self.log("Recording stopped but no audio was captured.")
            return

        audio = np.concatenate(self.mic_chunks, axis=0)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = REC / f"microphone_reference_{stamp}.wav"
        sf.write(str(path), audio, self.mic_samplerate, subtype="PCM_16")
        self._append_ref(self._make_voice_ref(path, recorded=True))
        self.update_ref_list()
        duration = len(audio) / float(self.mic_samplerate)
        self.log(f"Saved microphone reference: {path.name} | {duration:.1f}s | added to batch")

    def refresh_record_timer(self):
        if self.recording and self.record_started:
            sec = int(time.time() - self.record_started)
            self.rec_time.set(f"{sec // 60:02d}:{sec % 60:02d}")
        elif not self.recording:
            self.rec_time.set("00:00")
        self.root.after(250, self.refresh_record_timer)

    # ---------- logs/UI ----------
    def log(self, s):
        line = f"[{time.strftime('%H:%M:%S')}] {s}"
        self.q.put(("log", line))
        try:
            with (LOG / "voice_cloner.log").open("a", encoding="utf-8") as h:
                h.write(line + "\n")
        except Exception:
            pass

    def pump(self):
        try:
            while True:
                kind, data = self.q.get_nowait()
                if kind == "log":
                    self.lb.configure(state="normal")
                    self.lb.insert("end", data + "\n")
                    self.lb.see("end")
                    self.lb.configure(state="disabled")
                elif kind == "status":
                    self.status.set(data)
                elif kind == "progress":
                    value, maximum = data
                    self.pb.configure(maximum=maximum, value=value)
                elif kind == "done":
                    self.busy = False
                    self.go.configure(state="normal")
                    self.status.set(data)
        except queue.Empty:
            pass
        self.root.after(100, self.pump)

    def get_model(self):
        if self.model is None:
            self.q.put(("status", "Loading Chatterbox Turbo on RTX GPU..."))
            self.log("Loading Chatterbox Turbo on CUDA...")
            self.model = ChatterboxTurboTTS.from_pretrained(device="cuda")
            self.log("Model loaded.")
        return self.model

    # ---------- generation ----------
    def start_batch(self):
        if self.recording:
            messagebox.showinfo("Recording", "Stop the microphone recording first.")
            return
        if self.busy:
            return

        valid_refs = [ref for ref in self.refs if ref.path.exists()]
        if not valid_refs:
            messagebox.showinfo("Reference voices", "Add or record at least one reference voice first.")
            return

        missing_count = len(self.refs) - len(valid_refs)
        if missing_count:
            self.log(f"Skipping {missing_count} missing reference file(s).")

        # Chatterbox Turbo hard-asserts that the prompt must be > 5 seconds.
        # Catch it before loading/generating so one short file cannot kill a large batch.
        too_short = []
        unknown_duration = []
        for ref in valid_refs:
            duration = self.reference_duration(ref.path)
            if duration is None:
                unknown_duration.append(ref)
            elif duration <= 5.0:
                too_short.append((ref, duration))

        if too_short:
            preview = "\n".join(
                f"• {ref.language_label} / {ref.display_name}: {duration:.2f}s"
                for ref, duration in too_short[:12]
            )
            extra = "" if len(too_short) <= 12 else f"\n…and {len(too_short) - 12} more."
            messagebox.showerror(
                "Reference audio too short",
                "Chatterbox Turbo requires every reference prompt to be longer than 5 seconds.\n\n"
                f"These file(s) are too short:\n{preview}{extra}\n\n"
                "Replace them with longer references before generating."
            )
            self.log(f"Batch blocked: {len(too_short)} reference file(s) are <= 5 seconds.")
            return

        if unknown_duration:
            self.log(
                f"Could not preflight duration for {len(unknown_duration)} reference file(s); "
                "Turbo will validate those files during generation."
            )

        text = self.txt.get("1.0", "end").strip()
        if not text:
            messagebox.showinfo("Text", "Enter text to generate.")
            return

        try:
            takes = max(1, min(10, int(self.takes.get())))
        except Exception:
            takes = 3
        try:
            base_seed = int(self.seed.get())
        except Exception:
            base_seed = 4200

        settings = {
            "temperature": float(self.temperature.get()),
            "top_p": float(self.top_p.get()),
            "top_k": int(self.top_k.get()),
            "repetition_penalty": float(self.repetition_penalty.get()),
            "norm_loudness": bool(self.norm_loudness.get()),
        }

        self.busy = True
        self.go.configure(state="disabled")
        self.pb.configure(value=0, maximum=len(valid_refs) * takes)

        threading.Thread(
            target=self.batch_worker,
            args=(valid_refs, text, takes, base_seed, settings),
            daemon=True
        ).start()

    def rebuild_existing_audition(self):
        """Add the selector page to an already-generated batch without regenerating audio."""
        selected = filedialog.askdirectory(
            title="Choose an existing generated batch folder",
            initialdir=str(OUT),
        )
        if not selected:
            return

        batch = Path(selected)
        manifest = batch / "generation_manifest.json"
        if not manifest.exists():
            messagebox.showerror(
                "Existing batch",
                "That folder does not contain generation_manifest.json.\n\n"
                "Choose one of the generated batch folders inside the cloner output folder."
            )
            return

        try:
            rows = json.loads(manifest.read_text(encoding="utf-8"))
            if not isinstance(rows, list) or not rows:
                raise ValueError("The generation manifest is empty or invalid.")

            for row in rows:
                if not isinstance(row, dict):
                    continue
                voice_id = str(row.get("voice_id") or "").strip().lower()
                info = KOKORO_VOICE_INFO.get(voice_id)
                if info:
                    row["gender"] = row.get("gender") or info.get("gender", "")
                    row["style"] = row.get("style") or info.get("style", "")
                else:
                    row.setdefault("gender", "")
                    row.setdefault("style", "")

            text_file = batch / "generation_text.txt"
            generation_text = text_file.read_text(encoding="utf-8").strip() if text_file.exists() else ""

            audition = batch / "AUDITION.html"
            if audition.exists():
                backup = batch / "AUDITION_before_selection.html"
                if not backup.exists():
                    shutil.copy2(audition, backup)

            self.write_batch_manifests(batch, rows)
            audition = self.write_audition_page(batch, rows, generation_text)
            self.log(f"Rebuilt existing audition page: {audition}")

            if self.start_audition_server(batch):
                self.q.put(("status", "Existing audition rebuilt with Keep/Copy selection tools"))
            else:
                os.startfile(audition)
                messagebox.showinfo(
                    "Audition rebuilt",
                    "The page was rebuilt. If Copy Checked is unavailable, run OPEN_AUDITION.bat "
                    "inside that batch folder."
                )
        except Exception as exc:
            self.log(traceback.format_exc())
            messagebox.showerror("Existing batch", f"Could not rebuild the audition page:\n{exc}")

    def write_batch_manifests(self, batch: Path, rows):
        if not rows:
            return
        fields = [
            "language_group", "language_label", "voice_name", "voice_id", "gender", "style",
            "take", "seed", "reference_file", "reference_duration_sec",
            "output_file", "output_duration_sec", "generation_sec", "cuda_peak_gb"
        ]
        with (batch / "generation_manifest.csv").open("w", newline="", encoding="utf-8-sig") as h:
            writer = csv.DictWriter(h, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        (batch / "generation_manifest.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    def write_audition_page(self, batch: Path, rows, text: str):
        groups = defaultdict(lambda: defaultdict(list))
        voice_meta = {}
        for row in rows:
            group_key = row["language_group"] or "Uncategorized"
            voice_key = (row["voice_name"], row["voice_id"])
            groups[group_key][voice_key].append(row)
            voice_meta[(group_key, voice_key)] = row

        def e(value):
            return html.escape(str(value), quote=True)

        sections = []
        for group_name in sorted(groups, key=str.lower):
            voices = groups[group_name]
            label_values = {
                voice_meta[(group_name, voice_key)].get("language_label")
                for voice_key in voices
                if voice_meta.get((group_name, voice_key), {}).get("language_label")
            }
            pretty_group = next(iter(label_values)) if len(label_values) == 1 else humanize_group(group_name)
            voice_cards = []
            for voice_key in sorted(voices, key=lambda item: (item[0].lower(), item[1].lower())):
                voice_name, voice_id = voice_key
                meta = voice_meta[(group_name, voice_key)]
                gender = str(meta.get("gender") or "").strip()
                style = str(meta.get("style") or "").strip()
                attr_bits = [bit for bit in (gender, style) if bit]
                attrs = " · ".join(attr_bits)
                if not attrs:
                    attrs = str(meta.get("language_label") or pretty_group)

                selection_key = f"{group_name}|{voice_name}|{voice_id}"
                takes_html = []
                for row in sorted(voices[voice_key], key=lambda item: int(item["take"])):
                    src = quote(str(row["output_file"]).replace("\\", "/"), safe="/")
                    takes_html.append(
                        '<div class="take">'
                        '<label class="keep-wrap">'
                        f'<input class="keep" type="checkbox" data-voice-key="{e(selection_key)}" '
                        f'data-file="{e(row["output_file"])}" data-take="{int(row["take"])}">'
                        '<span>Keep</span>'
                        '</label>'
                        f'<div class="take-label">Take {int(row["take"]):02d} · seed {e(row["seed"])}</div>'
                        f'<audio controls preload="none" src="{src}"></audio>'
                        '</div>'
                    )
                voice_id_html = f'<span class="voice-id">{e(voice_id)}</span>' if voice_id else ""
                voice_cards.append(
                    '<section class="voice-card">'
                    f'<h3>{e(voice_name)} {voice_id_html}</h3>'
                    f'<div class="attributes">{e(attrs)}</div>'
                    + "".join(takes_html)
                    + '</section>'
                )
            sections.append(
                '<section class="language">'
                f'<h2>{e(pretty_group)} <span>{e(group_name)}</span></h2>'
                f'<div class="voice-grid">{"".join(voice_cards)}</div>'
                '</section>'
            )

        voice_count = len({(r["language_group"], r["voice_name"], r["voice_id"]) for r in rows})
        style_note = e(KOKORO_STYLE_NOTE)
        page = f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Chatterbox Turbo Batch Audition</title>
<style>
:root {{ color-scheme: dark; font-family: "Segoe UI", Arial, sans-serif; }}
body {{ margin: 0; background: #15171a; color: #f3f4f6; }}
main {{ max-width: 1450px; margin: 0 auto; padding: 28px; }}
h1 {{ margin: 0 0 8px; font-size: 30px; }}
.sub {{ color: #aeb4bd; margin-bottom: 14px; }}
.note {{ color: #aeb4bd; font-size: 13px; line-height: 1.45; margin: 8px 0 20px; }}
.prompt {{ background: #20242a; border: 1px solid #343a43; border-radius: 10px; padding: 14px 16px; margin-bottom: 18px; line-height: 1.5; }}
.toolbar {{ position: sticky; top: 0; z-index: 20; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; background: rgba(21,23,26,.96); border: 1px solid #343a43; border-radius: 10px; padding: 12px; margin: 0 0 22px; backdrop-filter: blur(8px); }}
button {{ border: 1px solid #55606d; background: #2b3139; color: #fff; padding: 9px 14px; border-radius: 8px; cursor: pointer; font-weight: 600; }}
button.primary {{ background: #2563eb; border-color: #3b82f6; }}
button:hover {{ filter: brightness(1.12); }}
button:disabled {{ opacity: .5; cursor: not-allowed; }}
#selectionCount {{ color: #c4c9d0; font-size: 14px; }}
#exportStatus {{ width: 100%; min-height: 18px; color: #9fd3a8; font-size: 13px; }}
#exportStatus.error {{ color: #ff9f9f; }}
.language {{ margin: 28px 0 38px; }}
h2 {{ border-bottom: 1px solid #353b44; padding-bottom: 9px; margin-bottom: 15px; }}
h2 span {{ color: #8f98a5; font-size: 14px; font-weight: 400; margin-left: 8px; }}
.voice-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(390px, 1fr)); gap: 14px; }}
.voice-card {{ background: #20242a; border: 1px solid #343a43; border-radius: 12px; padding: 14px; transition: border-color .15s, box-shadow .15s; }}
.voice-card:has(.keep:checked) {{ border-color: #4f86f7; box-shadow: 0 0 0 1px rgba(79,134,247,.22); }}
.voice-card h3 {{ margin: 0 0 3px; font-size: 19px; }}
.voice-id {{ color: #9aa3af; font-size: 13px; font-weight: 400; margin-left: 5px; }}
.attributes {{ color: #aeb7c3; font-size: 13px; margin-bottom: 12px; }}
.take {{ display: grid; grid-template-columns: 68px 116px 1fr; align-items: center; gap: 9px; margin: 8px 0; border-radius: 8px; padding: 4px 6px; }}
.take:has(.keep:checked) {{ background: rgba(37,99,235,.13); }}
.keep-wrap {{ display: flex; align-items: center; gap: 5px; cursor: pointer; font-size: 13px; color: #dce5f5; }}
.keep {{ width: 18px; height: 18px; accent-color: #3b82f6; cursor: pointer; }}
.take-label {{ color: #c4c9d0; font-size: 13px; }}
audio {{ width: 100%; height: 36px; }}
@media (max-width: 650px) {{ .voice-grid {{ grid-template-columns: 1fr; }} .take {{ grid-template-columns: 68px 1fr; }} .take audio {{ grid-column: 1 / -1; }} }}
</style>
</head>
<body>
<main>
<h1>Chatterbox Turbo Batch Audition</h1>
<div class="sub">{len(rows)} generated take(s) · {voice_count} voice(s)</div>
<div class="prompt"><strong>Generation text</strong><br>{e(text)}</div>
<div class="note"><strong>Voice attributes:</strong> {style_note}</div>
<div class="toolbar">
  <button class="primary" id="copyChecked">Copy checked to Selected_Previews</button>
  <button id="clearChecked">Clear checks</button>
  <span id="selectionCount">0 voice(s) selected</span>
  <div id="exportStatus"></div>
</div>
{''.join(sections)}
</main>
<script>
const checks = Array.from(document.querySelectorAll('.keep'));
const countEl = document.getElementById('selectionCount');
const statusEl = document.getElementById('exportStatus');
const copyBtn = document.getElementById('copyChecked');
const storageKey = 'chatterbox-selection:' + location.pathname;

function selected() {{ return checks.filter(c => c.checked); }}
function updateCount() {{
  const n = selected().length;
  countEl.textContent = `${{n}} voice(s) selected`;
  copyBtn.disabled = n === 0;
}}
function persist() {{
  try {{ localStorage.setItem(storageKey, JSON.stringify(selected().map(c => c.dataset.file))); }} catch (_) {{}}
}}
function restore() {{
  try {{
    const saved = new Set(JSON.parse(localStorage.getItem(storageKey) || '[]'));
    checks.forEach(c => c.checked = saved.has(c.dataset.file));
  }} catch (_) {{}}
  updateCount();
}}

checks.forEach(c => c.addEventListener('change', () => {{
  if (c.checked) {{
    checks.forEach(other => {{
      if (other !== c && other.dataset.voiceKey === c.dataset.voiceKey) other.checked = false;
    }});
  }}
  statusEl.textContent = '';
  statusEl.classList.remove('error');
  persist();
  updateCount();
}}));

document.getElementById('clearChecked').addEventListener('click', () => {{
  checks.forEach(c => c.checked = false);
  persist(); updateCount();
  statusEl.textContent = 'Selection cleared.';
  statusEl.classList.remove('error');
}});

copyBtn.addEventListener('click', async () => {{
  const files = selected().map(c => c.dataset.file);
  if (!files.length) return;
  statusEl.textContent = 'Copying selected previews...';
  statusEl.classList.remove('error');
  copyBtn.disabled = true;
  try {{
    const response = await fetch('/api/copy-selected', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{files}})
    }});
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || `HTTP ${{response.status}}`);
    statusEl.textContent = `Copied ${{data.count}} selected voice(s) to ${{data.destination}}`;
  }} catch (err) {{
    statusEl.classList.add('error');
    if (location.protocol === 'file:') {{
      statusEl.textContent = 'Copy requires the local audition server. Run OPEN_AUDITION.bat in this batch folder, then use the page it opens.';
    }} else {{
      statusEl.textContent = 'Copy failed: ' + err.message;
    }}
  }} finally {{ updateCount(); }}
}});

restore();
</script>
</body>
</html>'''
        path = batch / "AUDITION.html"
        path.write_text(page, encoding="utf-8")
        self.write_audition_server(batch)
        return path

    def write_audition_server(self, batch: Path):
        """Write a stdlib-only localhost helper so checked takes can be copied safely."""
        server_code = r'''from __future__ import annotations

import csv
import json
import shutil
import threading
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BATCH = Path(__file__).resolve().parent
MANIFEST = BATCH / "generation_manifest.json"
DEST = BATCH / "SELECTED_PREVIEWS"


def safe_name(value: str) -> str:
    result = "".join(c if c.isalnum() or c in "-_ " else "_" for c in str(value)).strip()
    return result.replace(" ", "_") or "voice"


def safe_group(value: str) -> Path:
    raw = str(value or "Uncategorized").replace("\\", "/").strip("/")
    parts = [safe_name(p) for p in raw.split("/") if p and p != "."]
    return Path(*parts) if parts else Path("Uncategorized")


def load_manifest():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BATCH), **kwargs)

    def log_message(self, fmt, *args):
        pass

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/api/copy-selected":
            self.send_json(404, {"ok": False, "error": "Unknown endpoint"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 1024 * 1024:
                raise ValueError("Invalid request size")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            wanted = payload.get("files") if isinstance(payload, dict) else None
            if not isinstance(wanted, list) or not wanted:
                raise ValueError("No selected files were supplied")

            rows = load_manifest()
            allowed = {str(r.get("output_file", "")).replace("\\", "/"): r for r in rows}
            selected = []
            seen_voice = set()
            for value in wanted:
                key = str(value).replace("\\", "/")
                row = allowed.get(key)
                if row is None:
                    raise ValueError(f"Selection is not in the batch manifest: {key}")
                voice_key = (
                    str(row.get("language_group", "")),
                    str(row.get("voice_name", "")),
                    str(row.get("voice_id", "")),
                )
                if voice_key in seen_voice:
                    raise ValueError(f"More than one take was selected for {row.get('voice_name') or 'a voice'}")
                seen_voice.add(voice_key)
                selected.append(row)

            if DEST.exists():
                shutil.rmtree(DEST)
            DEST.mkdir(parents=True, exist_ok=True)

            exported = []
            for row in selected:
                rel = str(row["output_file"]).replace("\\", "/")
                src = (BATCH / rel).resolve()
                try:
                    src.relative_to(BATCH.resolve())
                except ValueError:
                    raise ValueError("Unsafe output path in manifest")
                if not src.is_file():
                    raise FileNotFoundError(rel)

                group = safe_group(row.get("language_group") or "Uncategorized")
                out_dir = DEST / group
                out_dir.mkdir(parents=True, exist_ok=True)
                voice_name = safe_name(row.get("voice_name") or src.stem)
                voice_id = safe_name(row.get("voice_id") or "") if row.get("voice_id") else ""
                filename = f"{voice_name}__{voice_id}.wav" if voice_id else f"{voice_name}.wav"
                dest = out_dir / filename
                shutil.copy2(src, dest)

                item = dict(row)
                item["selected_preview_file"] = dest.relative_to(BATCH).as_posix()
                exported.append(item)

            (DEST / "selected_manifest.json").write_text(
                json.dumps(exported, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            if exported:
                fields = list(exported[0].keys())
                with (DEST / "selected_manifest.csv").open("w", newline="", encoding="utf-8-sig") as handle:
                    writer = csv.DictWriter(handle, fieldnames=fields)
                    writer.writeheader()
                    writer.writerows(exported)

            self.send_json(200, {
                "ok": True,
                "count": len(exported),
                "destination": str(DEST),
            })
        except Exception as exc:
            self.send_json(400, {"ok": False, "error": str(exc)})


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}/AUDITION.html"
    print("Audition page:", url)
    print("Selected previews:", DEST)
    threading.Timer(0.35, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
'''
        (batch / "audition_server.py").write_text(server_code, encoding="utf-8")
        launcher = r'''@echo off
setlocal
cd /d "%~dp0"
set "PY=%~dp0..\..\.venv\Scripts\python.exe"
if exist "%PY%" (
  "%PY%" audition_server.py
) else (
  python audition_server.py
)
'''
        (batch / "OPEN_AUDITION.bat").write_text(launcher, encoding="utf-8")

    def start_audition_server(self, batch: Path):
        """Launch the generated helper so the browser can safely copy checked takes."""
        helper = batch / "audition_server.py"
        try:
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.Popen(
                [sys.executable, str(helper)],
                cwd=str(batch),
                creationflags=creationflags,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except Exception as exc:
            self.log(f"Could not start audition helper automatically: {exc}")
            return False

    def batch_worker(self, refs, text, takes, base_seed, settings):
        try:
            model = self.get_model()
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            batch = OUT / f"{stamp}_batch_{len(refs)}voices_{takes}takes"
            batch.mkdir(parents=True)

            (batch / "generation_text.txt").write_text(text, encoding="utf-8")
            (batch / "reference_files.txt").write_text(
                "\n".join(
                    f"{ref.language_label}\t{ref.display_name}\t{ref.voice_id}\t{ref.path}"
                    for ref in refs
                ),
                encoding="utf-8"
            )
            (batch / "settings.txt").write_text(
                "\n".join(f"{k}={v}" for k, v in settings.items()),
                encoding="utf-8"
            )

            total = len(refs) * takes
            current = 0
            manifest_rows = []

            self.log(
                "Turbo settings: "
                f"temperature={settings['temperature']}, top_p={settings['top_p']}, "
                f"top_k={settings['top_k']}, repetition_penalty={settings['repetition_penalty']}, "
                f"norm_loudness={settings['norm_loudness']}"
            )

            for voice_index, ref in enumerate(refs, start=1):
                group_dir = batch / safe_group_path(ref.group_path)
                group_dir.mkdir(parents=True, exist_ok=True)

                voice_folder = f"{voice_index:02d}_{safe_name(ref.display_name)}"
                if ref.voice_id:
                    voice_folder += f"_{safe_name(ref.voice_id)}"
                voice_dir = group_dir / voice_folder
                voice_dir.mkdir(parents=True, exist_ok=True)
                ref_duration = self.reference_duration(ref.path)

                for take in range(1, takes + 1):
                    current += 1
                    seed = base_seed + (voice_index * 100) + take

                    self.q.put((
                        "status",
                        f"{ref.language_label} | {ref.display_name} | "
                        f"take {take}/{takes} | overall {current}/{total}"
                    ))

                    seed_all(seed)
                    torch.cuda.empty_cache()
                    torch.cuda.reset_peak_memory_stats()

                    start = time.perf_counter()
                    wav = model.generate(
                        text,
                        audio_prompt_path=str(ref.path),
                        temperature=settings["temperature"],
                        top_p=settings["top_p"],
                        top_k=settings["top_k"],
                        repetition_penalty=settings["repetition_penalty"],
                        norm_loudness=settings["norm_loudness"],
                    )
                    torch.cuda.synchronize()
                    elapsed = time.perf_counter() - start

                    wav = wav.detach().cpu()
                    if wav.ndim == 1:
                        wav = wav.unsqueeze(0)

                    fn = voice_dir / f"{safe_name(ref.display_name)}_take_{take:02d}_seed_{seed}.wav"
                    ta.save(str(fn), wav, model.sr)

                    duration = wav.shape[-1] / float(model.sr)
                    peak = torch.cuda.max_memory_allocated() / 1024**3
                    manifest_rows.append({
                        "language_group": ref.group_path,
                        "language_label": ref.language_label,
                        "voice_name": ref.display_name,
                        "voice_id": ref.voice_id,
                        "gender": ref.gender,
                        "style": ref.style,
                        "take": take,
                        "seed": seed,
                        "reference_file": str(ref.path),
                        "reference_duration_sec": round(ref_duration, 3) if ref_duration is not None else "",
                        "output_file": fn.relative_to(batch).as_posix(),
                        "output_duration_sec": round(duration, 3),
                        "generation_sec": round(elapsed, 3),
                        "cuda_peak_gb": round(peak, 3),
                    })
                    self.log(
                        f"{ref.language_label} / {ref.display_name} -> {fn.name} | "
                        f"{duration:.2f}s audio | {elapsed:.2f}s generation | {peak:.2f} GB CUDA"
                    )
                    self.q.put(("progress", (current, total)))

            self.write_batch_manifests(batch, manifest_rows)
            audition = self.write_audition_page(batch, manifest_rows, text)
            self.log(f"Batch complete: {batch}")
            self.log(f"Audition page: {audition}")
            if self.start_audition_server(batch):
                self.log("Audition selection helper started on localhost.")
                self.q.put(("done", "Finished - audition page opened with selection tools"))
            else:
                try:
                    os.startfile(audition)
                except Exception:
                    os.startfile(batch)
                self.q.put(("done", "Finished - audition page opened (run OPEN_AUDITION.bat to enable Copy Checked)"))
        except Exception:
            self.log(traceback.format_exc())
            self.q.put(("done", "Failed - see log"))


root = tk.Tk()
App(root)
root.mainloop()
