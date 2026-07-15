from odoo.tests import TransactionCase


class TestCommon(TransactionCase):

    def setUp(self):
        super(TestCommon, self).setUp()
        self.social_media_1 = self.env['social.media'].create({
            'name': 'Facebook Media',
            'social_provider': 'facebook'
        })
        self.social_page_1 = self.env['social.page'].create({
            'name': 'Page Odoo Test',
            'media_id': self.social_media_1.id
        })
        self.social_article_1 = self.env['social.article'].create({
            'name': 'Test',
            'message': 'test',
            'page_ids': [(6, 0, [self.social_page_1.id])],
            'attachment_type': 'file'
        })
        self.attachment_1 = self.env['ir.attachment'].create({
            'name': 'image test'
        })
