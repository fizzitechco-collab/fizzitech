"""Offline tests for stop/cancel/retry; no network or user files are used."""
import tempfile
from pathlib import Path
from unittest import mock
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from studio import jobs

with tempfile.TemporaryDirectory(prefix='peakcut-stop-test-') as td:
    root=Path(td)
    with mock.patch.object(jobs.ctx,'uid',return_value='cancel_test'),mock.patch.object(jobs.ctx,'bump'),mock.patch.object(jobs.config,'user_dir',return_value=root):
        j=jobs.create({'type':'url','url':'https://www.youtube.com/watch?v=test', 'name':'test'}, {}, enqueue=False)
        assert j['status']=='queued'
        jobs.cancel(j['id'])
        assert j['status']=='cancelled'
        assert not jobs._jobs[j['id']]['clips']
        try:
            jobs._check_cancel(j)
            raise AssertionError('cancel should interrupt')
        except jobs.JobCancelled:
            pass
        assert (jobs.job_dir(j['id'])/'job.json').is_file()
        fresh=jobs.retry(j['id'])
        assert fresh['status']=='queued' and fresh['id']!=j['id']
        assert j['status']=='cancelled'
        j2=jobs.create({'type':'url','url':'https://www.youtube.com/watch?v=test2', 'name':'test2'}, {},enqueue=False)
        j2['status']='running'
        jobs.cancel(j2['id'])
        assert j2['status']=='cancelling'
        try:
            jobs._set(j2,progress=0.7)
            raise AssertionError('cancel should stop updates')
        except jobs.JobCancelled:
            pass
        assert j2['status']=='cancelling'
        assert jobs.get(j2['id']) is j2
        try:
            jobs.retry(j2['id'])
            raise AssertionError('retry must reject running jobs')
        except ValueError:
            pass
        print('PASS queued cancellation, running checkpoints and retry')
        # uploaded file retry retains own copy; old file unaffected
        old=jobs.create({'type':'file','path':'', 'name':'demo.mp4'}, {},enqueue=False)
        src=jobs.job_dir(old['id'])/'source.mp4';src.write_bytes(b'12345')
        old['source']['path']=str(src)
        old['status']='error'
        cloned=jobs.retry(old['id'])
        assert Path(cloned['source']['path']).read_bytes()==b'12345'
        assert Path(cloned['source']['path'])!=src
        print('PASS local file retry preserves source and creates independent copy')
print('ALL PASSED')
with tempfile.TemporaryDirectory(prefix='peakcut-clip-stop-') as td:
    root=Path(td)
    with mock.patch.object(jobs.ctx,'uid',return_value='cancel_test'),mock.patch.object(jobs.ctx,'bump'),mock.patch.object(jobs.config,'user_dir',return_value=root):
        j=jobs.create({'type':'url','url':'https://www.youtube.com/watch?v=test', 'name':'test'}, {}, enqueue=False)
        j['clips']=[{'id':'clip01','status':'queued'},{'id':'clip02','status':'rendering'},{'id':'clip03','status':'done'}]
        jobs.cancel_clip(j['id'],'clip01')
        jobs.cancel_clip(j['id'],'clip02')
        assert [x['status'] for x in j['clips']]==['cancelled','stopping','done']
        assert not j.get('cancel_requested')
        try:
            jobs._check_clip(j,j['clips'][1]);raise AssertionError('clip cancellation checkpoint')
        except jobs.JobCancelled:pass
        print('PASS per-clip cancellation preserves other clips')
