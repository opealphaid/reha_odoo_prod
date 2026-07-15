from unittest.mock import patch

from odoo.tests import tagged
from odoo.addons.base.models.ir_attachment import IrAttachment

from .test_common import TestCommon


@tagged('post_install', '-at_install')
class TestSocialArticle(TestCommon):

    def test_compute_display_facebook_preview(self):
        self.social_article_1.page_ids = False
        self.assertFalse(self.social_article_1.display_facebook_preview)

        self.social_article_1.page_ids = self.social_page_1
        self.assertTrue(self.social_article_1.display_facebook_preview)

    @patch.object(IrAttachment, 'write', lambda self, vals: super(IrAttachment, self).write(vals))
    def test_action_confirm(self):
        # case 1:
        self.social_article_1.attachment_type = 'none'
        self.social_article_1.action_confirm()

        # case 2:
        self.attachment_1.write({
            'mimetype': 'image/png',
            'file_size': 5 * 1024 * 1024
        })

        # case 4:
        self.attachment_1.write({
            'mimetype': 'image/png',
            'file_size': 2 * 1024 * 1024
        })
        self.social_article_1.action_confirm()
