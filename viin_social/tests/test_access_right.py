try:
    # try to use UniqueViolation if psycopg2's version >= 2.8
    from psycopg2 import errors
    UniqueViolation = errors.UniqueViolation
except Exception:
    import psycopg2
    UniqueViolation = psycopg2.IntegrityError

from odoo.tests import tagged
from odoo.tools import mute_logger
from .common import Common
from odoo.exceptions import AccessError, UserError


@tagged('post_install', '-at_install', 'access_rights')
class TestAccessRight(Common):

    def test_social_article_user_editor_access_right(self):
        self.social_article_1.with_user(self.user_editor).read(['id'])
        self.env['social.article'].with_user(self.user_editor).create({
            'name': 'test',
            'message': 'test'
        })
        with self.assertRaises(AccessError):
            self.social_article_1.with_user(self.user_editor).unlink()
        with self.assertRaises(AccessError):
            self.social_article_1.with_user(self.user_editor).name = 'test 2'

        self.social_article_1.assign_id = self.user_editor
        self.social_article_1.with_user(self.user_editor).name = 'test 2'

        self.social_article_1.author_id = self.user_editor
        self.social_article_1.with_user(self.user_editor).unlink()

    def test_social_article_user_approve_access_right(self):
        self.social_article_1.with_user(self.user_approve).read(['id'])
        self.env['social.article'].with_user(self.user_editor).create({
            'name': 'test',
            'message': 'test'
        })
        self.social_article_1.with_user(self.user_approve).name = 'test 2'
        self.social_article_1.with_user(self.user_approve).unlink()

    def test_social_article_user_admin_access_right(self):
        self.social_article_1.with_user(self.user_admin).read(['id'])
        self.env['social.article'].with_user(self.user_admin).create({
            'name': 'test',
            'message': 'test'
        })
        self.social_article_1.with_user(self.user_admin).name = 'test 2'
        self.social_article_1.with_user(self.user_admin).unlink()

    def test_social_page_user_editor_access_right(self):
        self.social_page_1.with_user(self.user_editor).read(['id'])

        with self.assertRaises(AccessError):
            self.env['social.page'].with_user(self.user_editor).create({'name': 'page test'})
        with self.assertRaises(AccessError):
            self.social_page_1.with_user(self.user_editor).name = 'page 2'
        with self.assertRaises(AccessError):
            self.social_page_1.with_user(self.user_editor).unlink()

    def test_social_page_user_approve_access_right(self):
        self.social_page_1.with_user(self.user_approve).read(['id'])

        with self.assertRaises(AccessError):
            self.env['social.page'].with_user(self.user_approve).create({'name': 'page test'})
        with self.assertRaises(AccessError):
            self.social_page_1.with_user(self.user_approve).unlink()

        self.social_page_1.assign_id = self.user_approve
        self.social_page_1.with_user(self.user_approve).name = 'page 2'

    def test_social_page_user_admin_access_right(self):
        self.social_page_1.with_user(self.user_admin).read(['id'])
        self.social_page_1.with_user(self.user_admin).name = 'page 3'
        self.env['social.page'].with_user(self.user_admin).create({'name': 'page test 3'})
        self.social_page_1.post_ids.with_user(self.user_admin).unlink()
        self.social_page_1.with_user(self.user_admin).unlink()

    def test_social_post_user_editor_access_right(self):
        self.social_post_1.with_user(self.user_editor).read(['id'])
        with self.assertRaises(AccessError):
            self.env['social.page'].with_user(self.user_editor).create({'page_id': self.social_page_1.id})
        with self.assertRaises(UserError):
            self.social_post_1.with_user(self.user_editor).message = 'test'
        with self.assertRaises(UserError):
            self.social_post_1.with_user(self.user_editor).unlink()

    def test_social_post_user_approve_access_right(self):
        self.social_post_1.with_user(self.user_approve).read(['id'])
        with self.assertRaises(AccessError):
            self.env['social.page'].with_user(self.user_approve).create({'page_id': self.social_page_1.id})
        with self.assertRaises(UserError):
            self.social_post_1.with_user(self.user_approve).message = 'test'
        with self.assertRaises(UserError):
            self.social_post_1.with_user(self.user_editor).unlink()

    def test_social_post_user_admin_access_right(self):
        self.social_post_1.with_user(self.user_admin).read(['id'])
        self.env['social.post'].with_user(self.user_admin).create({'page_id': self.social_page_1.id})
        self.social_post_1.with_user(self.user_admin).message = 'test'
        self.social_post_1.with_user(self.user_admin).unlink()

    def test_social_notice_user_editor_access_right(self):
        self.social_page_1.member_ids = [(4, self.user_editor.id, 0)]
        self.social_notice_1.with_user(self.user_editor).read(['id'])
        with self.assertRaises(AccessError):
            self.env['social.notice'].with_user(self.user_editor).create({})
        with self.assertRaises(AccessError):
            self.social_notice_1.with_user(self.user_editor).unlink()

    def test_social_notice_user_approve_access_right(self):
        self.social_page_1.member_ids = [(4, self.user_approve.id, 0)]
        self.social_notice_1.with_user(self.user_approve).read(['id'])
        with self.assertRaises(AccessError):
            self.env['social.notice'].with_user(self.user_approve).create({})
        with self.assertRaises(AccessError):
            self.social_notice_1.with_user(self.user_approve).unlink()

    def test_social_notice_user_admin_access_right(self):
        self.social_notice_1.with_user(self.user_admin).read(['id'])
        with self.assertRaises(AccessError):
            self.env['social.notice'].with_user(self.user_admin).create({})

    def test_social_media_user_editor_access_right(self):
        self.social_media_1.with_user(self.user_editor).read(['id'])
        with self.assertRaises(AccessError):
            self.social_media_1.with_user(self.user_editor).name = 'test'
        with self.assertRaises(AccessError):
            self.env['social.media'].with_user(self.user_editor).create({'name': 'test'})
        with self.assertRaises(AccessError):
            self.social_media_1.with_user(self.user_editor).unlink()

    def test_social_media_user_approve_access_right(self):
        self.social_media_1.with_user(self.user_approve).read(['id'])
        with self.assertRaises(AccessError):
            self.social_media_1.with_user(self.user_approve).name = 'test'
        with self.assertRaises(AccessError):
            self.env['social.media'].with_user(self.user_approve).create({'name': 'test'})
        with self.assertRaises(AccessError):
            self.social_media_1.with_user(self.user_approve).unlink()

    def test_social_media_user_admin_access_right(self):
        self.social_media_1.with_user(self.user_admin).read(['id'])
        self.social_media_1.with_user(self.user_admin).name = 'test'
        with mute_logger('odoo.sql_db'):
            with self.assertRaises(UniqueViolation):
                self.env['social.media'].with_user(self.user_admin).create({'name': 'test'})
