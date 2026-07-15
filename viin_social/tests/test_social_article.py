from odoo.tests import tagged
from .common import Common
from odoo.exceptions import UserError


@tagged('-at_install', 'post_install')
class TestSocialArticle(Common):

    def test_01_compute_can_cancel(self):
        self.social_article_1.write({
            'assign_id': self.user_editor.id,
            'page_ids': [(6, 0, self.social_page_1.ids)]
        })
        social_article = self.social_article_1.with_user(self.user_editor)
        social_article.state = 'confirmed'
        self.assertEqual(social_article.can_cancel, False)

    def test_02_compute_can_cancel(self):
        self.social_article_1.write({
            'assign_id': self.user_approve.id,
            'page_ids': [(6, 0, self.social_page_1.ids)]
        })
        social_article = self.social_article_1.with_user(self.user_approve)
        social_article.state = 'confirmed'
        self.assertEqual(social_article.can_cancel, True)

    def test_03_compute_can_cancel(self):
        self.social_article_1.write({
            'assign_id': self.user_admin.id,
            'page_ids': [(6, 0, self.social_page_1.ids)]
        })
        social_article = self.social_article_1.with_user(self.user_admin)
        social_article.state = 'confirmed'
        self.assertEqual(social_article.can_cancel, True)

    def test_compute_post_count(self):
        # case 5:
        self.social_article_1.post_ids = self.social_post_1
        self.assertEqual(self.social_article_1.post_count, 1)

        self.social_article_1.post_ids = self.social_post_1 + self.social_post_2
        self.assertEqual(self.social_article_1.post_count, 2)

    def test_compute_message_view_more(self):
        # case 6:
        self.social_article_1.message = 't' * 140 + 'HH'
        self.assertTrue('HH' not in self.social_article_1.message_view_more)

        self.social_article_1.message = 'message test'
        self.assertFalse(self.social_article_1.message_view_more)

    def test_unlink(self):
        # case 7:
        self.social_article_1.state = 'confirmed'
        with self.assertRaises(UserError):
            self.social_article_1.unlink()

    def test_action_draft(self):
        self.social_article_1.state = 'confirmed'
        self.social_article_1.action_draft()
        self.assertEqual(self.social_article_1.state, 'draft')

    def test_01_action_confirm(self):
        # case 1:
        self.social_article_1.page_ids = False
        with self.assertRaises(UserError):
            self.social_article_1.action_confirm()

    def test_02_action_confirm(self):
        # case 8:
        self.social_article_1.write({
            'page_ids': [(6, 0, self.social_page_1.ids)],
            'attachment_type': 'file'
        })
        with self.assertRaises(UserError):
            self.social_article_1.action_confirm()

    def test_03_action_confirm(self):
        # case 9:
        self.assertEqual(len(self.social_article_1.post_ids), 0)

        self.social_article_1.page_ids = self.social_page_1
        self.social_article_1.action_confirm()

        self.assertEqual(len(self.social_article_1.post_ids), 1)
        self.assertEqual(self.social_article_1.state, 'confirmed')

    def test_01_action_cancel(self):
        # case 10:
        self.social_article_1.write({
            'assign_id': self.user_editor.id,
            'post_ids': [(6, 0, self.social_post_1.ids)]
        })
        self.social_article_1.with_user(self.user_editor).action_cancel()
        self.assertFalse(bool(self.social_post_1.exists()))
        self.assertEqual(self.social_article_1.state, 'cancelled')

    def test_02_action_cancel(self):
        # case 11:
        self.social_post_1.state = 'posted'
        self.social_article_1.post_ids = self.social_post_1
        with self.assertRaises(UserError):
            self.social_article_1.with_user(self.user_editor).action_cancel()

    def test_03_action_cancel(self):
        # case 13:
        self.social_post_1.state = 'posted'
        self.social_article_1.post_ids = self.social_post_1
        self.social_article_1.with_user(self.user_admin).action_cancel()

        self.assertFalse(bool(self.social_post_1.exists()))
        self.assertEqual(self.social_article_1.state, 'cancelled')

    def test_create_article(self):
        social_article = self.env['social.article'].create({
            'name': 'article with attachment',
            'message': 'article with attachment',
            'attachment_type': 'file',
            'attachment_ids': self.attachments[0].ids
        })
        self.assertEqual(social_article.attachment_ids.res_id, social_article.id)
        social_article.with_user(self.user_editor).read()

    def test_create_post(self):
        social_post = self.env['social.post'].create({
            'name': 'post with attachment',
            'message': 'post with attachment',
            'attachment_type': 'file',
            'attachment_ids': self.attachments.ids,
            'page_id': self.social_page_1.id
        })
        self.assertEqual(social_post.attachment_ids.mapped('res_id'), [social_post.id, social_post.id])
        social_post.with_user(self.user_editor).read()
