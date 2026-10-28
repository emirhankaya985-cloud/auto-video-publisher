import unittest
from content_hashtags import prepare_caption, selected_tags, TAG

class HashtagTests(unittest.TestCase):
    def test_platform_limits_and_unicode(self):
        text = 'Aşk sevgi özlem hasret ayrılık şiir yalnızlık umut arkadaş okul aile absürt ironi caps nostalji'
        self.assertEqual(len(selected_tags(text, 'gonle', '1', 'facebook')), 20)
        self.assertEqual(len(TAG.findall(prepare_caption(text, 'gonle', '1', 'instagram'))), 5)
    def test_unrelated_people_and_domains_not_inferred(self):
        self.assertNotIn('#KemalSunal', selected_tags('Yoksul', 'film', 'Yoksul_1986_Part_1', 'facebook'))
        self.assertNotIn('#Yoksul1986', selected_tags('Yoksul bir hayat', 'gonle', '1', 'facebook'))
        self.assertNotIn('#Mordecai', selected_tags('Funny clip', 'toonzone', 'S01E01_Part1', 'facebook'))
    def test_explicit_context_and_english(self):
        tags = selected_tags('Kemal_Sunal', 'film', 'Yoksul_1986_Part_1', 'facebook')
        self.assertIn('#KemalSunal', tags)
        self.assertIn('#Yoksul1986', tags)
        self.assertIn('#PetComedy', selected_tags('funny cat', 'daily_laugh', '1', 'facebook'))
        self.assertNotIn('#Aşk', selected_tags('love', 'daily_laugh', '1', 'facebook'))
    def test_mentions_idempotence_and_existing_tag_limit(self):
        value = 'Hi @cristiano\n' + ' '.join('#tag'+str(i) for i in range(30))
        out = prepare_caption(value, 'tarladaki', '1', 'instagram')
        self.assertIn('@cristiano', out)
        self.assertLessEqual(len(TAG.findall(out)), 5)
        self.assertEqual(out, prepare_caption(out, 'tarladaki', '1', 'instagram'))
    def test_no_truncation_or_unknown_route_change(self):
        value = 'x'*2198
        self.assertEqual(prepare_caption(value, 'gonle', '1', 'instagram'), value)
        self.assertEqual(prepare_caption('original #tag', 'unknown', '1', 'instagram'), 'original #tag')
