from .directory import DirectoryConnector
from .oracle_hr import OracleHRConnector
from .utrain import UTrainConnector


def all_connectors():
    return [DirectoryConnector(), UTrainConnector(), OracleHRConnector()]
