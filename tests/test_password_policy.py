"""Password boundaries and shared composition checks use actual Argon2id."""
from html.parser import HTMLParser
from pathlib import Path
import unittest
from hemlock.auth import password_hash, password_verify, PASSWORD_MIN_LENGTH, PASSWORD_MAX_LENGTH
from hemlock.domain import Invalid


class PasswordPolicyTests(unittest.TestCase):
    def test_boundaries_letters_digits_and_optional_specials(self):
        for value in ('abcde1', 'ABCDE1', 'a'+'1'*1023, 'парол1', 'abcd1!', ' a1   '):
            with self.subTest(length=len(value), kind='numeric' if value.isdigit() else 'text'):
                hashed = password_hash(value)
                self.assertTrue(hashed.startswith('$argon2id$v=19$m=65536,t=3,p=4$'))
                self.assertTrue(password_verify(hashed,value))
        self.assertNotEqual(password_hash('abcde1'),password_hash('abcde1'))
        for value in ('', 'abcd1', 'a'+'1'*1024, '123456', 'abcdef', 'ABCDEF', '!!!!!!', '      ', '1234!!', 123456, None):
            with self.assertRaises(Invalid):
                password_hash(value)

    def test_existing_hash_remains_valid_for_login(self):
        from argon2 import PasswordHasher
        legacy = '123456789012'
        self.assertTrue(password_verify(PasswordHasher().hash(legacy), legacy))
        with self.assertRaises(Invalid):
            password_hash(legacy)

    def test_browser_new_password_fields_match_server_boundaries(self):
        fields = {}
        class Inputs(HTMLParser):
            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag == 'input' and attrs.get('name') in ('password','new_password','repeat') and attrs.get('autocomplete') == 'new-password':
                    fields[attrs['name']] = attrs
        Inputs().feed((Path(__file__).parents[1]/'hemlock/static/index.html').read_text())
        self.assertEqual(set(fields), {'password','new_password','repeat'})
        for field in fields.values():
            self.assertEqual(int(field['minlength']), PASSWORD_MIN_LENGTH)
            self.assertEqual(int(field['maxlength']), PASSWORD_MAX_LENGTH)
            self.assertNotIn('pattern',field)
