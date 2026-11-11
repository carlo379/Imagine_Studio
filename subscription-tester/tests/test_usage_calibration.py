import unittest
import usage_calibration as uc

def job(n,resolution,duration,before,after,created=None,after_at=None,status='done',mock=False):
    created=created if created is not None else n*100
    return {'id':f'j{n}','created_at':created,'mock':mock,'status':status,'settings':{'resolution':resolution,'duration':duration},
            'usage':{'before':before,'after':after,'after_at':after_at if after_at is not None else created+50}}

class UsageCalibrationTests(unittest.TestCase):
    def test_three_agreeing_samples_establish_a_resolution(self):
        jobs=[job(1,'720p',5,10,11),job(2,'720p',10,11,13.2),job(3,'720p',5,13.2,14.3)]
        res=uc.calibration(jobs)['resolutions']['720p']
        self.assertTrue(res['established']);self.assertEqual(res['clean_samples'],3)
        self.assertAlmostEqual(res['percent_per_second'],0.22,places=3)
        self.assertAlmostEqual(res['estimate_percent']['10'],2.2,places=2)
        self.assertFalse(uc.required(jobs,'720p'));self.assertTrue(uc.required(jobs,'480p'))
    def test_disagreeing_samples_need_more_until_the_cap(self):
        jobs=[job(1,'480p',5,0,1),job(2,'480p',5,1,4),job(3,'480p',5,4,5)]
        self.assertFalse(uc.calibration(jobs)['resolutions']['480p']['established'])
        jobs+=[job(4,'480p',5,5,6),job(5,'480p',5,6,9),job(6,'480p',5,9,10)]
        res=uc.calibration(jobs)['resolutions']['480p']
        self.assertTrue(res['established']);self.assertIn('median',res['note'])
    def test_resets_overlaps_failures_and_mock_are_not_samples(self):
        jobs=[job(1,'720p',5,40,2),                                   # weekly reset
              job(2,'720p',5,2,3,created=200,after_at=400),job(3,'720p',5,3,4,created=300),  # overlap
              job(4,'720p',5,4,5,status='error'),job(5,'720p',5,5,6,mock=True),job(6,'720p',5,6,None)]
        result=uc.calibration(jobs)
        self.assertEqual(result['resolutions']['720p']['clean_samples'],0)
        self.assertEqual(sorted(r['discarded'] for r in result['samples']),
            ['another generation ran between the readings','another generation ran between the readings','usage went down (weekly reset?)'])
    def test_takes_below_the_meter_resolution_establish_zero(self):
        jobs=[job(n,'480p',3,7,7) for n in (1,2,3)]
        res=uc.calibration(jobs)['resolutions']['480p']
        self.assertTrue(res['established']);self.assertEqual(res['percent_per_second'],0);self.assertIn('meter',res['note'])
    def test_readings_are_validated(self):
        for bad in (True,-1,101,'5'):
            with self.assertRaises(ValueError):uc.reading(bad,'usage_before_percent')
        self.assertEqual(uc.reading(5,'x'),5.0);self.assertIsNone(uc.reading(None,'x'))

if __name__=='__main__':unittest.main()
