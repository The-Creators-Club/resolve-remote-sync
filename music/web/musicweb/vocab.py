"""The label vocabulary CLAP scores every track against.

This is the tuning surface. Edit it, then run `index_music.py --retag` to
re-score the whole library from stored embeddings (seconds, no audio decode).

It lives in `musicweb`, not in the indexer, since 2026-08-18
(docs/MUSIC_INGEST_PLAN.md step 2). Tagging is library-relative and now happens
on the NAS as well as on the base rig: an editor's companion embeds a dropped
track with the exported CLAP audio tower and the CONTAINER turns that embedding
into tags with the text tower it already loads for queries (`musicweb/rescore.py`).
That code needs this vocabulary, and the container has no `music_index` on its
PYTHONPATH -- the indexer is deliberately not part of the web deployment. So
the vocabulary moved to the tree that both halves share, exactly as `db.py`
and `schema.sql` already had. `music_index/vocab.py` is now a two-line alias to
this module and says so.

Each label carries several descriptive captions rather than one bare word.
CLAP was trained on natural-language captions, so "a tense suspenseful score
with a ticking pulse" discriminates far better than the single word "tense".
The label's text embedding is the mean of its captions.

Aimed at documentary / factual editing (Finding Formosa, CIB, MOFA), which is
why the vocabulary leans on editorial function and East Asian instrumentation
rather than dance-floor subgenres.
"""

CATEGORIES = {
    'genre': {
        'orchestral':      ['orchestral film score', 'a full symphony orchestra performing a cinematic score', 'sweeping orchestral music with strings and brass'],
        'ambient':         ['ambient atmospheric music', 'a slow evolving ambient soundscape', 'calm ambient pads with no clear beat'],
        'electronic':      ['electronic music', 'a produced electronic track with synthesizers', 'modern electronic production'],
        'synthwave':       ['retro synthwave music', 'analogue synthesizer arpeggios in an eighties style', 'nostalgic retro synth soundtrack'],
        'hip hop':         ['hip hop instrumental', 'a boom bap beat with drums and bass', 'downtempo hip hop groove'],
        'rock':            ['rock music with electric guitars and drums', 'a driving rock band performance', 'distorted guitar rock'],
        'post-rock':       ['post-rock with slow building guitars', 'atmospheric guitar music building to a crescendo', 'cinematic post rock'],
        'folk acoustic':   ['acoustic folk music', 'fingerpicked acoustic guitar folk', 'gentle acoustic instrumental with organic instruments'],
        'jazz':            ['jazz music', 'a jazz ensemble with upright bass and brushed drums', 'smoky lounge jazz'],
        'classical':       ['classical chamber music', 'a classical piano or string quartet piece', 'baroque or romantic classical music'],
        'east asian':      ['traditional East Asian music', 'traditional Chinese instrumental music with erhu and guzheng', 'Japanese traditional music with koto and shakuhachi'],
        'world folk':      ['traditional world folk music', 'ethnic folk instruments from a non-western tradition', 'indigenous traditional music'],
        'lo-fi':           ['lo-fi music with tape hiss', 'a warm lo-fi beat with vinyl crackle', 'hazy lo-fi instrumental'],
        'pop':             ['upbeat pop instrumental', 'a bright modern pop backing track', 'catchy commercial pop music'],
        'trailer epic':    ['epic trailer music', 'huge hybrid trailer score with braams and percussion', 'blockbuster movie trailer music'],
        'choral':          ['choral music with human voices', 'a choir singing wordless harmonies', 'sacred vocal choral music'],
        'experimental':    ['experimental sound design music', 'abstract textural music with unconventional sounds', 'avant garde processed audio'],
        'blues soul':      ['blues music', 'soulful blues guitar and organ', 'slow soul groove'],
    },

    'mood': {
        'tense':           ['tense suspenseful music', 'an anxious score with a ticking pulse', 'nervous music that builds unease'],
        'ominous':         ['dark ominous music', 'a foreboding score suggesting danger', 'menacing low drones and threat'],
        'dark':            ['dark brooding music', 'a heavy sombre score', 'bleak dark atmosphere'],
        'uplifting':       ['uplifting inspiring music', 'a bright optimistic and encouraging score', 'positive rising and hopeful music'],
        'hopeful':         ['hopeful gentle music', 'a tender score suggesting quiet optimism', 'warm hopeful melody'],
        'triumphant':      ['triumphant heroic music', 'a victorious fanfare of success', 'proud soaring heroic score'],
        'melancholy':      ['melancholy sad music', 'a sorrowful reflective piece', 'wistful mournful score'],
        'nostalgic':       ['nostalgic music evoking memory', 'a wistful score recalling the past', 'bittersweet nostalgic melody'],
        'peaceful':        ['peaceful calm music', 'a serene tranquil piece', 'gentle relaxing and restful score'],
        'mysterious':      ['mysterious enigmatic music', 'a curious score full of questions', 'intriguing mysterious atmosphere'],
        'urgent':          ['urgent driving music', 'a relentless propulsive score with momentum', 'fast insistent chase music'],
        'playful':         ['playful quirky music', 'a light-hearted whimsical piece', 'fun bouncy and cheeky score'],
        'romantic':        ['romantic tender music', 'an intimate loving score', 'warm romantic strings'],
        'aggressive':      ['aggressive angry music', 'a violent forceful score', 'harsh confrontational music'],
        'contemplative':   ['contemplative reflective music', 'a thoughtful introspective piece', 'quiet music for considered thought'],
        'eerie':           ['eerie unsettling music', 'a creepy uncanny atmosphere', 'ghostly disturbing textures'],
        'grand':           ['grand majestic music', 'a sweeping monumental score', 'awe-inspiring vast and cinematic'],
        'lonely':          ['lonely isolated music', 'a sparse desolate score', 'solitary music suggesting emptiness'],
        'determined':      ['determined resolute music', 'a steady purposeful score of resolve', 'music suggesting quiet determination'],
    },

    'instrument': {
        'piano':           ['solo piano', 'a felt piano playing a simple melody', 'piano-led instrumental'],
        'strings':         ['string orchestra', 'lush violins violas and cellos', 'legato string ensemble'],
        'solo cello':      ['a solo cello', 'lone cello melody', 'intimate solo string instrument'],
        'acoustic guitar': ['acoustic guitar', 'fingerpicked steel string guitar', 'nylon string classical guitar'],
        'electric guitar': ['electric guitar', 'reverb-drenched electric guitar', 'distorted electric guitar riffs'],
        'synth':           ['synthesizer pads and leads', 'analogue synth textures', 'electronic synthesizer arpeggio'],
        'drums':           ['acoustic drum kit', 'a live drummer with kick snare and hi-hat', 'rhythmic drum groove'],
        'percussion':      ['ethnic hand percussion', 'taiko drums and large percussion hits', 'shakers congas and tribal drums'],
        'brass':           ['brass section', 'french horns and trumpets', 'heavy low brass'],
        'woodwind':        ['woodwind instruments', 'solo flute or clarinet', 'bamboo flute melody'],
        'choir':           ['a choir of human voices', 'wordless vocal ooohs and aaahs', 'ethereal vocal pads'],
        'electronic beat': ['programmed electronic drums', 'a synthetic drum machine beat', 'clicky electronic percussion'],
        'bass':            ['prominent bass line', 'deep sub bass', 'upright bass'],
        'east asian str':  ['erhu and guzheng', 'a plucked Chinese zither', 'traditional East Asian string instrument'],
        'mallets':         ['marimba and vibraphone', 'glockenspiel and music box', 'tuned mallet percussion'],
        'organ':           ['pipe organ', 'a hammond organ', 'church organ chords'],
        'harp':            ['harp glissandi', 'a solo harp', 'delicate plucked harp'],
    },

    'use_case': {
        'interview bed':   ['a subtle underscore for a spoken interview', 'unobtrusive background music beneath dialogue', 'a neutral bed that leaves room for a voice'],
        'montage':         ['music for a montage sequence', 'a rhythmic driving cue for a series of shots', 'energetic montage backing'],
        'opening titles':  ['opening title music for a documentary', 'a bold statement cue to open a film', 'main title theme'],
        'tension build':   ['a slow building tension cue', 'music that rises steadily towards a climax', 'a riser building anticipation'],
        'emotional payoff':['an emotional climax cue', 'music for a moving revelation', 'a heartfelt swelling emotional peak'],
        'action':          ['action sequence music', 'fast percussive chase music', 'high intensity action score'],
        'underscore':      ['quiet background underscore', 'understated music sitting low in a mix', 'a simple sustained bed'],
        'credits':         ['end credits music', 'a reflective closing cue', 'music to play over end titles'],
        'reveal':          ['a moment of discovery or revelation', 'music for an awe-struck reveal', 'a wondrous unveiling cue'],
        'timelapse':       ['music for a timelapse', 'steady pulsing motion music', 'a cue suggesting the passing of time'],
    },

    'texture': {
        'sparse':          ['sparse minimal music with few elements', 'a bare arrangement with lots of space', 'quiet and uncluttered'],
        'dense':           ['dense layered production', 'a thick wall of many instruments', 'busy full arrangement'],
        'lo-fi tape':      ['tape saturated lo-fi texture', 'warm analogue hiss and wobble', 'degraded vintage recording quality'],
        'clean':           ['clean polished modern production', 'a pristine studio recording', 'crisp and clear mix'],
        'gritty':          ['gritty distorted texture', 'overdriven saturated sound', 'raw abrasive production'],
        'pulsing':         ['a pulsing rhythmic ostinato', 'steady repeating pulse', 'insistent throbbing rhythm'],
        'drone':           ['a sustained drone', 'long held tones with no rhythm', 'static atmospheric drone bed'],
        'glitchy':         ['glitchy stuttering digital artefacts', 'chopped and processed audio', 'broken digital textures'],
    },
}

# Bipolar axes -> continuous scores. Stored raw and as a percentile rank
# within the library, because raw CLAP similarities are poorly calibrated in
# absolute terms but reliably ordered.
AXES = {
    'arousal': {
        'high': ['high energy intense powerful music', 'loud fast and exciting', 'an energetic driving climax'],
        'low':  ['calm quiet low energy music', 'slow soft and still', 'a sparse restful passage'],
    },
    'valence': {
        'high': ['happy positive uplifting music', 'bright cheerful and warm', 'joyful optimistic mood'],
        'low':  ['sad negative gloomy music', 'dark sorrowful and heavy', 'depressing bleak mood'],
    },
    'tension': {
        'high': ['tense anxious unresolved music', 'suspenseful and on edge', 'music full of dread and threat'],
        'low':  ['relaxed resolved settled music', 'comfortable and at ease', 'peaceful resolution'],
    },
    'organic': {
        'high': ['acoustic organic instruments played by humans', 'real recorded instruments in a room', 'natural unprocessed performance'],
        'low':  ['synthetic electronic computer-generated sound', 'programmed synthesizers and drum machines', 'artificial processed production'],
    },
}

# How many labels to keep per category per track.
TOP_K = {'genre': 3, 'mood': 4, 'instrument': 4, 'use_case': 3, 'texture': 3}

# Softmax temperature, applied to per-label z-scores (not raw similarities),
# so it is in units of standard deviations across the library. ~0.5 gives a
# clearly peaked distribution without collapsing to a single label.
TEMPERATURE = 0.5

# Per-label calibration strength, 0..1 (see tagging.score_all).
#   0.0 = raw similarity   -> reflects true library prevalence, but captions
#         that sit near the "average music" direction win everywhere
#   1.0 = full z-score     -> removes that bias, but forces every label to win
#         for roughly equal numbers of tracks, which distorts a library that
#         genuinely is mostly orchestral
# Tuned on eval.py; partial shrinkage beats either extreme.
CALIBRATION = 0.5


def all_prompts():
    """Every caption that needs a text embedding, in a stable order."""
    out = []
    for cat, labels in CATEGORIES.items():
        for label, phrases in labels.items():
            for p in phrases:
                out.append(('cat', cat, label, p))
    for axis, poles in AXES.items():
        for pole, phrases in poles.items():
            for p in phrases:
                out.append(('axis', axis, pole, p))
    return out


def vocab_hash():
    import hashlib, json
    blob = json.dumps([CATEGORIES, AXES, TOP_K, TEMPERATURE],
                      sort_keys=True, ensure_ascii=False)
    return hashlib.blake2b(blob.encode('utf-8'), digest_size=8).hexdigest()
