# Third-Party Notices

This project is a separate GUI/helper project built around third-party text-to-speech software and reference audio. Those projects retain their own names, copyrights and licenses.

## Chatterbox / Chatterbox Turbo

- Project: Resemble AI Chatterbox
- Package: `chatterbox-tts`
- Upstream repository: `https://github.com/resemble-ai/chatterbox`
- PyPI: `https://pypi.org/project/chatterbox-tts/`
- Upstream license: MIT

This repository does not vendor the Chatterbox Python package or model weights. They are installed/downloaded separately by the user.

## Kokoro-82M

- Model: Kokoro-82M by hexgrad
- Model page: `https://huggingface.co/hexgrad/Kokoro-82M`
- Upstream model license: Apache-2.0

The included Kokoro reference WAV package contains generated reference samples, not Kokoro model weights or `.pt` voice packs. See `voices/Kokoro Voices/README.md` and its metadata files for exact provenance and conversion notes.

## ghostreel source gallery

The Kokoro reference package documents `digitaldrywood/ghostreel` as the public gallery/source used for the generated samples and language/sample-text mapping.

- Repository: `https://github.com/digitaldrywood/ghostreel`
- Repository license: MIT

## Reference-audio rights

Model/software licensing and audio/voice rights are separate questions. Before redistributing any added reference recording, make sure you have the right to redistribute the recording and use the represented voice for cloning.

The eight `voices/builtin_*.wav` files were supplied with the local project and do not contain embedded provenance metadata identifying their source. Review their origin before publishing them in a public repository if you are not certain you have redistribution rights.
