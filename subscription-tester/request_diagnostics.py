"""Local exception locations without request bodies, images or credentials."""
import logging
import traceback
import uuid
from pathlib import Path


def structure_failure(error, operation):
    reference = uuid.uuid4().hex[:8]
    locations = ' > '.join(f'{Path(frame.filename).name}:{frame.lineno}:{frame.name}'
                           for frame in traceback.extract_tb(error.__traceback__))
    # The legacy OAuth harness globally disables logging. Emit this narrowly
    # scoped, input-free diagnostic even when provider logging is suppressed.
    logger = logging.getLogger('imagine.requests')
    logger.handle(logger.makeRecord('imagine.requests', logging.ERROR, __file__, 0,
        'Request %s: %s; %s; %s', (reference, operation, type(error).__name__, locations), None))
    return f'Imagine Studio could not {operation} because of an internal data error. Please retry. Error reference: {reference}.'


def writing_fallback(reason):
    """Use the same local logger, without prompts or reference inputs."""
    logger = logging.getLogger('imagine.requests')
    logger.handle(logger.makeRecord('imagine.requests', logging.WARNING, __file__, 0,
        'Prompt writer fallback to Grok: %s', (reason,), None))
