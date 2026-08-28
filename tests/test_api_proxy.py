import unittest

from request_validation import validate_messages


class ValidateMessagesTest(unittest.TestCase):
    def test_accepts_supported_roles_and_trims_content(self):
        messages = [
            {"role": "system", "content": " 规则 "},
            {"role": "user", "content": " 我家猫今天没吃饭 "},
        ]
        self.assertEqual(
            validate_messages(messages),
            [
                {"role": "system", "content": "规则"},
                {"role": "user", "content": "我家猫今天没吃饭"},
            ],
        )

    def test_rejects_empty_messages(self):
        with self.assertRaises(ValueError):
            validate_messages([])

    def test_rejects_unknown_role(self):
        with self.assertRaises(ValueError):
            validate_messages([{"role": "tool", "content": "test"}])

    def test_rejects_oversized_message(self):
        with self.assertRaises(ValueError):
            validate_messages([{"role": "user", "content": "x" * 6001}])


if __name__ == "__main__":
    unittest.main()
