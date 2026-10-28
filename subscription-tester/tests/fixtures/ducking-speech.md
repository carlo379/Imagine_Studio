# Licensed recorded-speech fixture

`ducking-speech.wav` contains LibriSpeech dev-clean utterance
`2277-149896-0026`, from speaker 2277, chapter 149896.

Attribution: Vassil Panayotov, Guoguo Chen, Daniel Povey and Sanjeev Khudanpur,
**LibriSpeech: an ASR corpus based on public domain audio books**, 2015.
The corpus is published under **Creative Commons Attribution 4.0 International**:

- Dataset and license: https://www.openslr.org/12/
- Source archive: https://www.openslr.org/resources/12/dev-clean.tar.gz
- Archive member: `LibriSpeech/dev-clean/2277/149896/2277-149896-0026.flac`
- License: https://creativecommons.org/licenses/by/4.0/
- Local license notice: [CC BY 4.0](../../../LICENSES/CC-BY-4.0.txt)

Changes: decoded FLAC to mono, 16 kHz signed 16-bit PCM WAV using FFmpeg.
No speech, image or video generation service was used. No endorsement by the
speakers, corpus authors or OpenSLR is implied. The recording remains CC BY 4.0,
separate from the application's MIT license.

Source FLAC SHA-256:
`3909a6c5ae93112518681fcbf0a74df43615a4f88bd6d5cd788775255296e3f6`

Bundled WAV SHA-256:
`c5617c8d07ac91a256b230e351e79041687b800c6e542788225509b3634f6cfd`

Tests use this fixed recording and never download it or invoke TTS. Ducking
checks measure 200 ms steady-speech windows with music isolated to the other
stereo channel; speech onsets and release tails are assessed separately.
