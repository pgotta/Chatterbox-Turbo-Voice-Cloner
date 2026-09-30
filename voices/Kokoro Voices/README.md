# Kokoro Voice Reference Pack for Chatterbox Turbo

This package contains **53 Kokoro voice reference WAV files** across the nine language variants shown in the Kokoro UI screenshots.

## Audio format

- WAV / PCM signed 16-bit little-endian
- 24,000 Hz
- Mono
- Natural speed (1.0)
- No EQ, denoising, pitch shifting or time stretching
- Short samples are extended only by repeating the original audio with a 180 ms gap
- Sample duration: **minimum 8.0 seconds**; most clips are roughly 8–13 seconds

These files are organized as clean reference clips for auditioning and voice-prompt use with Chatterbox Turbo. Every WAV is now safely longer than Chatterbox Turbo's hard 5-second audio-prompt minimum.


## Chatterbox Turbo compatibility fix

Chatterbox Turbo rejects reference audio at 5 seconds or shorter with:

`AssertionError: Audio prompt must be longer than 5 seconds!`

To prevent that error, any Kokoro sample shorter than 8 seconds was extended by repeating the same original Kokoro sample with a **180 ms silent gap** between passes. Samples already at least 8 seconds were left unchanged. This preserves the original voice, pitch and playback speed while giving Turbo a comfortable duration margin.

The repeated material is intentional conditioning audio. It is not meant to change the voice identity or the text you ask Chatterbox to generate.

## Important provenance / quality note

The source samples were generated with **Kokoro-82M / kokoro-onnx** by the public `digitaldrywood/ghostreel` Kokoro voice gallery. That gallery first generates WAV with Kokoro, then publishes the gallery copies as **mono 64 kbps MP3**. This package converts those published MP3 gallery samples back to **24 kHz mono PCM16 WAV** for Chatterbox-friendly reference files.

Because there is an MP3 intermediate, these are not bit-identical to the original lossless Kokoro WAV renders. They are clean Kokoro-generated voice samples, but the package does not claim the transcoding can restore information removed by MP3 compression.

Source project:
`https://github.com/digitaldrywood/ghostreel`

The exact sample text and language mapping come from `src/voices.py` in that project.

## Included voices

### English (American) — 19
Adam (`am_adam`), Puck (`am_puck`), Liam (`am_liam`), Heart (`af_heart`), Bella (`af_bella`), Jessica (`af_jessica`), Echo (`am_echo`), Eric (`am_eric`), Fenrir (`am_fenrir`), Michael (`am_michael`), Onyx (`am_onyx`), Santa (`am_santa`), Alloy (`af_alloy`), Aoede (`af_aoede`), Kore (`af_kore`), Nicole (`af_nicole`), Nova (`af_nova`), River (`af_river`), Sarah (`af_sarah`).

`af_sky` is intentionally excluded because it was not in the American English voice list you supplied.

### English (British) — 8
Alice (`bf_alice`), Emma (`bf_emma`), Isabella (`bf_isabella`), Lily (`bf_lily`), Daniel (`bm_daniel`), Fable (`bm_fable`), George (`bm_george`), Lewis (`bm_lewis`).

### Chinese (Simplified / Mandarin) — 8
Xiaobei (`zf_xiaobei`), Xiaoni (`zf_xiaoni`), Xiaoxiao (`zf_xiaoxiao`), Xiaoyi (`zf_xiaoyi`), Yunjian (`zm_yunjian`), Yunxi (`zm_yunxi`), Yunxia (`zm_yunxia`), Yunyang (`zm_yunyang`).

### French — 1
Siwis (`ff_siwis`).

### Hindi — 4
Alpha (`hf_alpha`), Beta (`hf_beta`), Omega (`hm_omega`), Psi (`hm_psi`).

### Italian — 2
Sara (`if_sara`), Nicola (`im_nicola`).

### Japanese — 5
Alpha (`jf_alpha`), Gongitsune (`jf_gongitsune`), Nezumi (`jf_nezumi`), Tebukuro (`jf_tebukuro`), Kumo (`jm_kumo`).

### Portuguese (Brazilian) — 3
Dora (`pf_dora`), Alex (`pm_alex`), Santa (`pm_santa`).

### Spanish — 3
Dora (`ef_dora`), Alex (`em_alex`), Santa (`em_santa`).

## Sample text used by language

**American English**  
This is a sample of the Kokoro voice. Choose the voice that fits your story.

**British English**  
This is a sample of the Kokoro voice. Choose the voice that suits your story.

**Spanish**  
Esta es una muestra de la voz Kokoro. Elige la voz que mejor se adapte a tu historia.

**French**  
Voici un exemple de la voix Kokoro. Choisissez la voix qui correspond à votre histoire.

**Hindi**  
यह कोकोरो आवाज़ का एक नमूना है। अपनी कहानी के लिए सही आवाज़ चुनें।

**Italian**  
Questo è un esempio della voce Kokoro. Scegli la voce più adatta alla tua storia.

**Japanese**  
これは音声サンプルです。

**Portuguese (Brazilian)**  
Esta é uma amostra da voz Kokoro. Escolha a voz que combina com a sua história.

**Chinese (Simplified / Mandarin)**  
这是一个语音示例。请选择适合您故事的声音。

## Metadata

`metadata/voices.json` and `metadata/voices.csv` include:

- Kokoro voice ID
- display name
- language / locale / accent variant
- gender
- reference description
- exact sample text
- WAV path
- duration
- sample rate / channels / bit depth
- SHA-256 hash
- source / conversion notes

`metadata/SHA256SUMS.txt` can be used to verify every WAV file.
