"""Retired bundled seed API: never reads or rewrites a user's historical data.

Current official catalogs and navigation are validated by their own source-bound
pipelines. No empty replacement seed is produced or required for packaging.
"""
from wlre.storage.resource_seed_manifest import SOURCE_MANIFEST, RETIRED_RESOURCES
SEED_NAME = 'resource_catalog_seed.sqlite3'


def _retired():
    raise ValueError('隨附離線導航種子已退役；請同步目前官方資料。既有使用者資料未修改。')


def verify_seed(path):
    _retired()


def build_seed(root, destination):
    _retired()


def provision_seed(seed, database):
    _retired()


def read_config(name, *, root):
    _retired()


def main(argv=None):
    _retired()


if __name__ == '__main__':main()
