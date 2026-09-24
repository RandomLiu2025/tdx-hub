import logging

formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
console = logging.StreamHandler()
console.setLevel(logging.INFO)
console.setFormatter(formatter)

logger = logging.getLogger("tdxhub.tdx")
logger.addHandler(console)
logger.setLevel(logging.INFO)
