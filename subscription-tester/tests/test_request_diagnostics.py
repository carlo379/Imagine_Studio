import unittest
import logging
from request_diagnostics import structure_failure


class RequestDiagnosticsTests(unittest.TestCase):
    def test_safe_diagnostic_survives_provider_logging_suppression(self):
        old=logging.root.manager.disable
        try:
            logging.disable(logging.CRITICAL)
            with self.assertLogs('imagine.requests', level='ERROR') as captured:
                structure_failure(KeyError('PRIVATE'), 'validate this video request')
            self.assertIn('KeyError',captured.output[0])
            self.assertNotIn('PRIVATE',captured.output[0])
        finally:logging.disable(old)
    def test_exception_location_is_logged_without_input_or_exception_text(self):
        try:
            raise KeyError('PRIVATE_IMAGE_OR_TOKEN')
        except KeyError as error:
            with self.assertLogs('imagine.requests', level='ERROR') as captured:
                message = structure_failure(error, 'update this shot’s selected take')
        self.assertIn('KeyError', captured.output[0])
        self.assertIn('test_request_diagnostics.py', captured.output[0])
        self.assertNotIn('PRIVATE_IMAGE_OR_TOKEN', captured.output[0] + message)
        self.assertIn('Error reference:', message)
        reference = message.split('Error reference: ')[1].rstrip('.')
        self.assertIn(reference, captured.output[0])
