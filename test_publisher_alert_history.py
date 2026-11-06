import copy
import json
import os
import tempfile
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import Mock,patch

import publisher_alert_history as a
import telegram_publish_report as report

NOW=datetime(2026,10,30,12,tzinfo=timezone.utc)
EVENT={'route':'film','platform':'instagram','video':'Part10.mp4','stage':'instagram_publish','reason':'invalid_media_or_graph_request'}


def history():return {'schema':1,'records':{}}
def descriptors():return a.incident_descriptors([EVENT])
def observe(h,rid='100',now=NOW):a.observe(h,descriptors(),{'entries':{}},rid,now=now)


class AlertHistoryTests(unittest.TestCase):
    def test_unchanged_incident_is_not_reserved_again_after_hours_or_days(self):
        h=history();observe(h)
        msg=a.reserve(h,'🚨 error','body',descriptors(),'100',now=NOW)
        self.assertIsNotNone(msg)
        a.mark_ack(h,msg,'telegram');a.mark_ack(h,msg,'ntfy')
        original=copy.deepcopy(next(iter(h['records'].values())))
        for index,hours in enumerate((1,24,25,48,168),101):
            later=NOW+timedelta(hours=hours);rid=str(index)
            observe(h,rid,later)
            before=copy.deepcopy(h)
            self.assertIsNone(a.reserve(h,'🚨 error','body',descriptors(),rid,now=later))
            self.assertEqual(h,before)  # no new intent or ACK reset
            row=next(iter(h['records'].values()))
            for field in ('last_intent','intent_run_id','server_acks','attempted_channels'):
                self.assertEqual(row[field],original[field])
            self.assertIn(rid,row['observed_runs'])
            self.assertFalse(row['resolved'])

    def test_distinct_incident_is_eligible_while_known_incident_remains_suppressed(self):
        h=history();observe(h)
        first=a.reserve(h,'error','body',descriptors(),'100',now=NOW)
        a.mark_ack(h,first,'telegram')
        original=copy.deepcopy(h['records'][first['keys'][0]])
        distinct=a.incident_descriptors([dict(EVENT,video='Part11.mp4')])
        later=NOW+timedelta(days=3)
        a.observe(h,distinct,{'entries':{}},'200',now=later)
        msg=a.reserve(h,'new incident','new body',distinct,'200',now=later)
        self.assertEqual(msg,{'title':'new incident','body':'new body','keys':list(distinct)})
        self.assertEqual(h['records'][first['keys'][0]],original)
        self.assertIsNone(a.reserve(h,'old incident','body',descriptors(),'200',now=later))

    def test_confirmed_resolution_then_recurrence_notifies_once_again(self):
        h=history();observe(h)
        first=a.reserve(h,'error','body',descriptors(),'100',now=NOW)
        a.mark_ack(h,first,'telegram')
        resolved=NOW+timedelta(days=1)
        done={'route':'film','platform':'instagram','file':'Part10.mp4',
              'status':'done','post_id':'123','run_id':'200'}
        a.observe(h,{}, {'entries':{'confirmed':done}},'200',now=resolved)
        key=first['keys'][0]
        self.assertTrue(h['records'][key]['resolved'])
        observe(h,'201',resolved+timedelta(minutes=1))
        recurrence=a.reserve(h,'recurrence','body',descriptors(),'201',now=resolved+timedelta(minutes=1))
        self.assertIsNotNone(recurrence)
        self.assertEqual(recurrence['title'],'recurrence')
        self.assertEqual(h['records'][key]['intent_run_id'],'201')
        self.assertEqual(h['records'][key]['server_acks'],[])
        self.assertFalse(h['records'][key]['resolved'])
        a.mark_ack(h,recurrence,'ntfy')
        observe(h,'202',resolved+timedelta(days=5))
        before=copy.deepcopy(h)
        self.assertIsNone(a.reserve(h,'recurrence','body',descriptors(),'202',now=resolved+timedelta(days=5)))
        self.assertEqual(h,before)

    def test_ambiguous_attempt_without_ack_does_not_authorize_daily_retry(self):
        h=history();observe(h)
        msg=a.reserve(h,'error','body',descriptors(),'100',now=NOW)
        row=h['records'][msg['keys'][0]]
        row['attempted_channels']=['telegram']
        for days in (1,2,7):
            later=NOW+timedelta(days=days)
            observe(h,str(100+days),later)
            before=copy.deepcopy(h)
            self.assertIsNone(a.reserve(h,'error','body',descriptors(),str(100+days),now=later))
            self.assertEqual(h,before)
            self.assertEqual(row['server_acks'],[])
            self.assertEqual(row['attempted_channels'],['telegram'])

    def test_held_intent_and_media_error_have_same_identity(self):
        held=dict(EVENT,stage='previous_intent_hold',reason='unreconciled_previous_intent')
        self.assertEqual(set(a.incident_descriptors([held])),set(descriptors()))
        self.assertNotEqual(set(a.incident_descriptors([dict(EVENT,video='Part11.mp4')])),set(descriptors()))
        self.assertNotEqual(set(a.incident_descriptors([dict(EVENT,reason='credentials_or_permissions')])),set(descriptors()))

    def test_posts_are_never_repeated_by_daily_reminder(self):
        h=history();k=a.identity('post',extra='123')
        ds={k:{'kind':'post','route':'film','platform':'facebook','video':'clip.mp4'}}
        a.observe(h,ds,{'entries':{}},'100',now=NOW)
        self.assertIsNotNone(a.reserve(h,'post','body',ds,'100',now=NOW))
        self.assertIsNone(a.reserve(h,'post','body',ds,'200',now=NOW+timedelta(days=2)))

    def test_health_requires_all_failed_runs_to_have_acked_incidents(self):
        h=history();observe(h)
        msg=a.reserve(h,'error','body',descriptors(),'100',now=NOW)
        observe(h,'101')
        self.assertFalse(a.covered(h,run_ids=['100','101'],now=NOW))
        a.mark_ack(h,msg,'telegram')
        self.assertTrue(a.covered(h,run_ids=['100','101'],now=NOW))
        self.assertFalse(a.covered(h,run_ids=['100','999'],now=NOW))
        self.assertFalse(a.covered(h,run_ids=['100'],now=NOW+timedelta(hours=7)))

    def test_target_coverage_is_route_and_platform_specific(self):
        h=history();observe(h);msg=a.reserve(h,'error','body',descriptors(),'100',now=NOW);a.mark_ack(h,msg,'ntfy')
        self.assertTrue(a.covered(h,route='film',platforms=['instagram'],now=NOW))
        self.assertFalse(a.covered(h,route='toonzone',platforms=['instagram'],now=NOW))
        self.assertFalse(a.covered(h,route='film',platforms=['instagram','facebook'],now=NOW))

    def test_only_current_confirmed_post_resolves_incident(self):
        h=history();observe(h)
        row={'route':'film','platform':'instagram','file':'Part10.mp4','status':'done','post_id':'123','run_id':'old'}
        a.observe(h,{}, {'entries':{'x':row}},'101',now=NOW)
        self.assertFalse(next(iter(h['records'].values()))['resolved'])
        row['run_id']='101'
        a.observe(h,{}, {'entries':{'x':row}},'101',now=NOW)
        self.assertTrue(next(iter(h['records'].values()))['resolved'])
        self.assertFalse(a.covered(h,run_ids=['100'],now=NOW))

    def test_failed_or_missing_archive_never_becomes_empty_history(self):
        for body in ({}, {'artifacts':'bad'}):
            response=Mock(status_code=200);response.json.return_value=body
            with patch.dict(os.environ,{'GH_TOKEN':'secret'}):
                with self.assertRaises(ValueError):a.restore(get=Mock(return_value=response))
        response=Mock(status_code=403)
        with patch.dict(os.environ,{'GH_TOKEN':'secret'}):
            with self.assertRaises(ValueError) as exc:a.restore(get=Mock(return_value=response))
            self.assertNotIn('secret',str(exc.exception))

    def test_first_run_empty_archive_is_explicit(self):
        response=Mock(status_code=200);response.json.return_value={'artifacts':[]}
        with patch.dict(os.environ,{'GH_TOKEN':'secret'}):self.assertEqual(a.restore(get=Mock(return_value=response)),history())

    def test_untrusted_archive_origin_cannot_suppress_alerts(self):
        listing=Mock(status_code=200);listing.json.return_value={'artifacts':[{'name':'link-alert-result','id':5,'workflow_run':{'id':100}}]}
        run=Mock(status_code=200);run.json.return_value={'head_branch':'feature','head_repository':{'full_name':a.REPO},'path':'.github/workflows/public_link_schedule.yml'}
        with patch.dict(os.environ,{'GH_TOKEN':'secret'}),self.assertRaises(ValueError):
            a.restore(get=Mock(side_effect=[listing,listing,run]))

    def test_prepare_sends_nothing_and_creates_stable_intents(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            with patch.object(a,'HISTORY',root/'alert-history.json'),patch.object(a,'PREPARED',root/'notifications.json'), \
                 patch.object(a,'restore',return_value=history()),patch.object(a,'now_utc',return_value=NOW), \
                 patch.object(report,'send_telegram') as telegram,patch.object(report,'send_ntfy') as ntfy, \
                 patch.dict(os.environ,{'GITHUB_OUTPUT':str(root/'outputs')}):
                result=report._prepare_durable([('error','body')],[],[EVENT],{'entries':{}},'100',telegram_on=True,ntfy_on=True,base_failures=0,category='alert')
                self.assertEqual(result,0);telegram.assert_not_called();ntfy.assert_not_called()
                self.assertEqual(len(a.read(a.PREPARED)['messages']),1)
                h=a.read(a.HISTORY);self.assertTrue(next(iter(h['records'].values()))['last_intent'])
                self.assertIn('alert_archive_needed=true',(root/'outputs').read_text())

    def _prepared(self,root):
        h=history();observe(h);msg=a.reserve(h,'error','body',descriptors(),'100',now=NOW)
        a.save(root/'history.json',h)
        a.save(root/'plan.json',{'run_id':'100','messages':[msg],'telegram':True,'ntfy':False,
            'base_failures':0,'confirmed_posts':0,'recorded_errors':1,'category':'alert'})

    def test_send_requires_archived_intent(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);self._prepared(root)
            with patch.object(a,'HISTORY',root/'history.json'),patch.object(a,'PREPARED',root/'plan.json'), \
                 patch.dict(os.environ,{'GITHUB_RUN_ID':'100','ALERT_INTENT_ARCHIVED':'false'}),patch.object(report,'send_telegram') as send:
                self.assertEqual(report._send_durable(),1);send.assert_not_called()

    def test_repeated_send_does_not_repeat_acknowledged_or_ambiguous_messages(self):
        for failure in (False,True):
            with tempfile.TemporaryDirectory() as td:
                root=Path(td);self._prepared(root)
                with patch.object(a,'HISTORY',root/'history.json'),patch.object(a,'PREPARED',root/'plan.json'), \
                     patch.dict(os.environ,{'GITHUB_RUN_ID':'100','ALERT_INTENT_ARCHIVED':'true'}), \
                     patch.object(report,'record_error'), \
                     patch.object(report,'send_telegram',side_effect=RuntimeError('sensitive') if failure else None,return_value={'server_ack':True}) as send:
                    report._send_durable();report._send_durable()
                    send.assert_called_once()
                    row=next(iter(a.read(a.HISTORY)['records'].values()))
                    self.assertEqual(row['server_acks'],[] if failure else ['telegram'])
                    self.assertEqual(row['attempted_channels'],['telegram'])

    def test_correlation_skips_only_acknowledged_health_alarm(self):
        import public_link_health as health
        with patch.dict(os.environ,{'CORRELATE_PUBLISHER_ALERTS':'true'}), \
             patch.object(health,'check_publisher',return_value={'status':'unhealthy','reason':'consecutive_failures','failed_run_ids':['100','101']}), \
             patch.object(a,'restore',return_value=history()),patch.object(a,'covered',return_value=True), \
             patch.object(health,'send_telegram') as send,patch.object(health,'send_ntfy') as ntfy:
            self.assertEqual(health.main(),1);send.assert_not_called();ntfy.assert_not_called()


if __name__=='__main__':unittest.main()
