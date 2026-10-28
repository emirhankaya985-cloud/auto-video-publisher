"""Deterministic topic tags; never guess usernames or alter old publication intents."""
import re
import unicodedata

TAG = re.compile(r'(?<!\w)#\w+', re.UNICODE)
LIMITS = {'facebook': 20, 'instagram': 5}
BASE = {
    'tarladaki': 'TarladakiFasulye Mizah Komedi TürkçeMizah KomikVideolar Eğlence Kahkaha İnternetMizahı',
    'penguen': 'BeyinsizPenguen Mizah Komedi TürkçeMizah KomikVideolar Eğlence İnternetMizahı',
    'gonle': 'GönleDüşen Duygular AnlamlıSözler KalptenSözler',
    'daily_laugh': 'DailyLaughLab Comedy FunnyVideos FunnyClips Humor FunnyMoments ComedyReels',
    'film': 'FilmMağarası TürkSineması FilmSahneleri Sinema FilmReplikleri',
    'film_second': 'Filmmagrasi TürkSineması FilmSahneleri Sinema FilmReplikleri',
    'toonzone': 'ToonZone RegularShow SürekliDizi ÇizgiFilm Animasyon ÇizgiDizi CartoonComedy AnimatedComedy RegularShowFans ÇizgiFilmSahneleri',
}
# Only explicit filename/caption cues activate these groups. No visual recognition.
GROUPS = [
    ('aşk ask sevda love', 'Aşk AşkSözleri Sevda'),
    ('sevgi love', 'Sevgi'), ('özlem ozlem hasret', 'Özlem Hasret'),
    ('ayrılık ayrilik breakup', 'Ayrılık'), ('şiir siir poem', 'Şiir ŞiirSözleri TürkçeŞiir'),
    ('yalnızlık yalnizlik lonely', 'Yalnızlık'), ('umut hope', 'Umut'),
    ('arkadaş arkadas friend', 'Arkadaşlık ArkadaşMizahı'),
    ('öğrenci ogrenci okul school student', 'ÖğrenciHayatı ÖğrenciMizahı OkulMizahı'),
    ('iş work office', 'İşHayatı'), ('aile family', 'AileMizahı'),
    ('absürt absurt absurd', 'AbsürtMizah'), ('ironi irony', 'İroni'),
    ('caps meme', 'Caps TürkçeCaps'), ('nostalji nostalgi', 'Nostalji'),
    ('yoksul yeşilçam yesilcam', 'Yoksul Yoksul1986 Yeşilçam YeşilçamKlasikleri KlasikTürkFilmleri'),
    ('kemalsunal kemal_sunal', 'KemalSunal'), ('şenerşen sener_sen', 'ŞenerŞen'),
    ('ilyassalman ilyas_salman', 'İlyasSalman'), ('münirözkul munir_ozkul', 'MünirÖzkul'),
    ('adilenaşit adile_nasit', 'AdileNaşit'),
    ('mordecai', 'Mordecai'), ('rigby', 'Rigby'), ('benson', 'Benson'),
    ('skips', 'Skips'), ('pops', 'Pops'), ('muscleman muscle_man', 'MuscleMan'),
    ('hifiveghost hi_five_ghost', 'HiFiveGhost'),
]
ENGLISH_GROUPS = [
    ('relatable', 'RelatableComedy'), ('everyday daily life', 'EverydayHumor'),
    ('situation', 'SituationalComedy'), ('unexpected surprise', 'UnexpectedEnding'),
    ('slapstick', 'Slapstick VisualComedy'), ('sketch', 'SketchComedy'),
    ('work office', 'WorkHumor'), ('school student', 'SchoolHumor'),
    ('friend', 'FriendshipHumor'), ('family', 'FamilyComedy'),
    ('pet cat dog animal', 'PetComedy AnimalComedy'),
]


def normalized(value):
    value = unicodedata.normalize('NFKD', value.casefold().replace('ı', 'i'))
    return ''.join(c for c in value if not unicodedata.combining(c))


def selected_tags(caption, route, stem, platform):
    if route not in BASE or platform not in LIMITS:
        return []
    context = normalized(stem + ' ' + caption)
    # Alphanumeric boundaries avoid matching 'iş' inside unrelated words.
    context = re.sub(r'[_#]', ' ', context)
    groups = ENGLISH_GROUPS if route == 'daily_laugh' else GROUPS
    topical = []
    for cues, tags in groups:
        if any(t in tags.split() for t in ('Yoksul', 'KemalSunal', 'ŞenerŞen', 'İlyasSalman', 'MünirÖzkul', 'AdileNaşit')) and route not in {'film', 'film_second'}:
            continue
        if any(t in tags.split() for t in ('Mordecai', 'Rigby', 'Benson', 'Skips', 'Pops', 'MuscleMan', 'HiFiveGhost')) and route != 'toonzone':
            continue
        if any(re.search(r'(?<!\w)' + re.escape(normalized(cue).replace('_', ' ')) + r'(?!\w)', context)
               for cue in cues.split()):
            topical.extend(tags.split())
    candidates = topical + BASE[route].split()
    result, seen = [], set()
    for tag in candidates:
        if tag.casefold() not in seen:
            result.append('#' + tag)
            seen.add(tag.casefold())
    return result[:LIMITS[platform]]


def prepare_caption(caption, route, stem, platform):
    tags = selected_tags(caption, route, stem, platform)
    if not tags:
        return caption
    body = TAG.sub('', caption).rstrip()
    # Preserve meaningful text/mentions. Drop optional tags before truncating text.
    while tags and len(body + '\n\n' + ' '.join(tags)) > (2200 if platform == 'instagram' else 63206):
        tags.pop()
    return body + ('\n\n' + ' '.join(tags) if tags else '')
