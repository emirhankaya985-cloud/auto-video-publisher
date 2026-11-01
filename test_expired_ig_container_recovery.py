import copy
import unittest
from unittest.mock import Mock
import expired_ig_container_recovery as recovery

class ExpiredContainerTests(unittest.TestCase):
    def setUp(self):
        # Immutable exact source/caption fixture; no production credentials.
        self.item = {'id': recovery.SOURCE_ID, 'name': recovery.FILE_NAME}
        self.entry = {'route': 'film', 'platform': 'instagram', 'status': 'uncertain', 'caption_hash': 'd7bfd2238b0de47372e0536e61c79545049346aa56a7a75b0d5e707a342d1417', 'file': 'Avanak_Apti_Part_10 (1).mp4', 'publish_caption': '🎬 Avanak Apti Part 10 (1978) 🤪🎞️\nKemal Sunal’dan saf mı saf, iyi niyetli mi iyi niyetli bir karakter: Apti!\nYanlış anlaşılmalar, talihsiz tesadüfler ve bitmeyen sakarlıklar…\nHer sahnesi ayrı kahkaha, her repliği ayrı efsane olan tam bir Yeşilçam komedisi! 😂\nGülmeye hazırsan doğru yerdesin!\nDevamı geliyor — takipte kal!\n🔗 https://miroviastudio.etsy.com\n👇 Bu unutulmaz sahne hakkında ne düşünüyorsun? Yorumlarda buluşalım!\n\n#Nostalji #Yeşilçam #YeşilçamKlasikleri #KlasikTürkFilmleri #KemalSunal', 'day': '2026-11-01', 'run_id': '41325257469', 'prepublish_retry_count': 2, 'container_resume': {'container_id': '17904577569599675', 'origin_run_id': '41036563337', 'caption_hash': 'd7bfd2238b0de47372e0536e61c79545049346aa56a7a75b0d5e707a342d1417', 'source_id': '1Zn8kYmexuUe3z1EKLtCrKFCwj4qVnIa2'}, 'resume_no_publish_confirmed': True}
        self.page = {'page_id': '1239298989276639', 'instagram_id': '17841477990224124', 'page_token': 'SECRET'}

    def response(self, status):
        res = Mock(status_code=200)
        res.json.return_value = {'id': recovery.CONTAINER_ID, 'status_code': status}
        return Mock(return_value=res)

    def test_exact_expired_one_time_authorization(self):
        get = self.response('EXPIRED')
        self.assertTrue(recovery.authorize_exact_expired_recovery('film','instagram', self.item,self.entry,self.page,history_reconciled=True,get=get))
        self.assertEqual(self.entry['status'],'ready')
        self.assertEqual(self.entry['prepublish_retry_count'],3)
        self.assertNotIn('container_resume',self.entry)
        self.assertTrue(recovery.terminal_recovery_reserved('film','instagram',self.item,self.entry))
        self.assertFalse(recovery.authorize_exact_expired_recovery('film','instagram',self.item,self.entry,self.page,history_reconciled=True,get=get))
        self.assertEqual(get.call_count,1)
        self.assertNotIn('SECRET', str(self.entry))

    def test_pending_published_errors_and_finished_are_never_authorized(self):
        for status in ('IN_PROGRESS','FINISHED','PUBLISHED','ERROR','UNVERIFIED'):
            before=copy.deepcopy(self.entry)
            self.assertFalse(recovery.authorize_exact_expired_recovery('film','instagram',self.item,self.entry,self.page,history_reconciled=True,get=self.response(status)))
            self.assertEqual(before,self.entry)

    def test_publish_ambiguity_history_or_source_mismatch_never_requests(self):
        for field,value in [('container_publish_attempted',True),('resume_no_publish_confirmed',False),('caption_hash','wrong'),('prepublish_retry_count',3)]:
            entry=copy.deepcopy(self.entry);entry[field]=value
            get=Mock()
            self.assertFalse(recovery.authorize_exact_expired_recovery('film','instagram',self.item,entry,self.page,history_reconciled=True,get=get))
            get.assert_not_called()
        get=Mock()
        self.assertFalse(recovery.authorize_exact_expired_recovery('film','instagram',self.item,self.entry,self.page,get=get))
        get.assert_not_called()

if __name__=='__main__':unittest.main()
