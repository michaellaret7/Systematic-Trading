import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

vhandler = logging.FileHandler("log.txt")
logger.addHandler(vhandler)

thandler = logging.FileHandler("log2.txt")
thandler.setLevel(logging.WARNING)
logger.addHandler(thandler)

logger.debug("This is a debug message")
logger.warning("This is a warning message")
