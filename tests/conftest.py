"""Browser acceptance is explicitly opted in; normal pytest remains the unit gate."""
def pytest_addoption(parser):
    parser.addoption('--run-e2e',action='store_true',default=False,help='Run real Chromium acceptance against isolated temporary databases')
    parser.addoption('--e2e-profile',choices=['all','desktop','mobile'],default='all')


def pytest_ignore_collect(collection_path,config):
    if collection_path.name in ('e2e','demo_e2e') and collection_path.parent.name=='tests' and not config.getoption('--run-e2e'):
        return True
