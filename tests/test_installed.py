"""Runtime metadata is independent of checkout version and optional VCS details."""
import unittest
from unittest.mock import Mock, patch
from importlib.metadata import PackageNotFoundError

from hemlock.installed import application_identity


class InstalledIdentityTests(unittest.TestCase):
    def test_installed_version_and_optional_commit(self):
        distribution = Mock(version='9.8.7')
        distribution.read_text.return_value = '{"vcs_info":{"commit_id":"'+'a'*40+'"}}'
        with patch('hemlock.installed.metadata.distribution',return_value=distribution):
            self.assertEqual(application_identity(),{'version':'9.8.7','build_commit':'a'*40})

    def test_no_commit_or_invalid_metadata_does_not_expose_urls(self):
        distribution = Mock(version='9.8.7')
        for value in (None,'invalid','[]','{"vcs_info":null}',
                      '{"url":"file:///private/location","vcs_info":{"commit_id":"unsafe value"}}'):
            distribution.read_text.return_value = value
            with self.subTest(value=value),patch('hemlock.installed.metadata.distribution',return_value=distribution):
                self.assertEqual(application_identity(),{'version':'9.8.7','build_commit':None})

    def test_no_installed_metadata_is_explicitly_unknown(self):
        with patch('hemlock.installed.metadata.distribution',side_effect=PackageNotFoundError):
            self.assertEqual(application_identity(),{'version':None,'build_commit':None})
