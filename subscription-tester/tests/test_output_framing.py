import io
import tempfile
import unittest
from PIL import Image
from studio_server import Studio


class OutputFramingTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.app=Studio(mock=True,storage=folder.name)
        self.addCleanup(self.app.productions.sql.close)
        self.draft=self.app.images.create({'title':'Framing','settings':{'model':'gpt-image-2','prompt':'Full body, feet visible.','ratio':'9:16'}})

    def output(self,size,format='PNG'):
        raw=io.BytesIO();Image.new('RGB',size,'blue').save(raw,format=format)
        return self.app.images.cache(raw.getvalue(),{'mock':True,'id':'synthetic','draft':self.draft})

    def test_real_pixel_size_and_exact_rounding_or_mismatch(self):
        exact=self.output((90,160))
        self.assertEqual((exact['width'],exact['height']),(90,160))
        self.assertTrue(exact['ratio_matches_request']);self.assertNotIn('framing_warning',exact)
        rounded=self.output((941,1672))
        self.assertIn('Minor pixel rounding',rounded['framing_warning'])
        self.assertLess(rounded['ratio_deviation_percent'],.1)
        square=self.output((160,160))
        self.assertFalse(square['ratio_matches_request'])
        self.assertIn('Review the framing',square['framing_warning'])
        for format in ('JPEG','WEBP'):
            with self.subTest(format=format):
                image=self.output((90,160),format)
                self.assertEqual((image['width'],image['height']),(90,160))

    def test_canvas_guidance_preserves_the_authored_framing(self):
        prompt=self.app.images.compile(self.draft)[1]['prompt']
        self.assertIn('Full body, feet visible.',prompt)
        self.assertIn('Requested output canvas: 9:16.',prompt)
        self.assertIn('do not zoom or crop merely',prompt)
        self.assertEqual(prompt.count('Requested output canvas:'),1)
