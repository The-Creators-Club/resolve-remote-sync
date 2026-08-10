"""CLAP wrapper: audio and text into one shared embedding space."""
import numpy as np
import torch

from music_index import config
# One definition, shared with the web app: the query side normalises text
# embeddings with the same function the index side normalises audio with.
from musicweb.projection import l2norm


class Clap:
    def __init__(self, name=None, device=None):
        from transformers import ClapModel, ClapProcessor
        self.device = device or ('cuda' if torch.cuda.is_available() else 'cpu')
        name = name or config.CLAP_MODEL
        try:
            self.model = ClapModel.from_pretrained(name)
            self.processor = ClapProcessor.from_pretrained(name)
            self.name = name
        except Exception as e:
            print(f'  ! {name} unavailable ({type(e).__name__}), '
                  f'falling back to {config.CLAP_FALLBACK}')
            self.model = ClapModel.from_pretrained(config.CLAP_FALLBACK)
            self.processor = ClapProcessor.from_pretrained(config.CLAP_FALLBACK)
            self.name = config.CLAP_FALLBACK
        self.model.eval().to(self.device)
        self.dim = int(self.model.config.projection_dim)

    @staticmethod
    def _vec(out):
        """get_*_features returns a bare tensor on transformers 4.x and a
        BaseModelOutputWithPooling on 5.x. The 512-d projected embedding is
        `pooler_output` in the latter."""
        if torch.is_tensor(out):
            return out
        for attr in ('text_embeds', 'audio_embeds', 'pooler_output'):
            v = getattr(out, attr, None)
            if v is not None and torch.is_tensor(v):
                return v
        raise TypeError(f'cannot extract embedding from {type(out).__name__}')

    def _audio_inputs(self, chunks):
        """transformers renamed `audios` -> `audio` across versions."""
        kw = dict(sampling_rate=config.SAMPLE_RATE, return_tensors='pt')
        try:
            return self.processor(audio=list(chunks), **kw)
        except TypeError:
            return self.processor(audios=list(chunks), **kw)

    @torch.no_grad()
    def embed_audio(self, chunks, batch_size=None):
        """chunks: list of 1-D float32 arrays at SAMPLE_RATE. -> (N, dim) unit vectors."""
        if not chunks:
            return np.zeros((0, self.dim), dtype=np.float32)
        bs = batch_size or config.BATCH_SIZE
        out = []
        for i in range(0, len(chunks), bs):
            inputs = self._audio_inputs(chunks[i:i + bs])
            inputs = {k: v.to(self.device) for k, v in inputs.items()}
            feats = self._vec(self.model.get_audio_features(**inputs))
            out.append(feats.float().cpu().numpy())
        return l2norm(np.concatenate(out, axis=0))

    @torch.no_grad()
    def embed_text(self, texts, batch_size=64):
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        out = []
        for i in range(0, len(texts), batch_size):
            inputs = self.processor(text=list(texts[i:i + batch_size]),
                                    return_tensors='pt', padding=True)
            inputs = {k: v.to(self.device) for k, v in inputs.items()}
            feats = self._vec(self.model.get_text_features(**inputs))
            out.append(feats.float().cpu().numpy())
        return l2norm(np.concatenate(out, axis=0))
