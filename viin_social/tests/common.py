from odoo.tests import TransactionCase


class Common(TransactionCase):

    def setUp(self):
        super(Common, self).setUp()
        Users = self.env['res.users'].with_context({'no_reset_password': True, 'mail_create_nosubscribe': True})
        self.attachments = self.env['ir.attachment'].create([{'name': 'photo1'}, {'name': 'photo2'}])

        self.user_editor = Users.create({
            'name': 'User Editor',
            'login': 'User Editor',
            'email': 'user.editor@example.viindoo.com',
            'groups_id': [(6, 0, [self.env.ref('viin_social.viin_social_group_editor').id])]
        })
        self.user_approve = Users.create({
            'name': 'User Approve',
            'login': 'User Approve',
            'email': 'user.approve@example.viindoo.com',
            'groups_id': [(6, 0, [self.env.ref('viin_social.viin_social_group_approve').id])]
        })
        self.user_admin = Users.create({
            'name': 'Social Marketing Admin',
            'login': 'User Admin',
            'email': 'user.admin@example.viindoo.com',
            'groups_id': [(6, 0, [self.env.ref('viin_social.viin_social_group_admin').id])]
        })

        self.social_page_1 = self.env['social.page'].create({
            'name': 'Page Facebook 1'
        })
        self.social_article_1 = self.env['social.article'].create({
            'name': 'social article test1',
            'message': 'message test'
        })
        self.social_post_1 = self.env['social.post'].create({
            'page_id': self.social_page_1.id
        })
        self.social_post_2 = self.env['social.post'].create({
            'page_id': self.social_page_1.id
        })
        self.social_notice_1 = self.env['social.notice'].create({
            'page_id': self.social_page_1.id
        })
        self.social_media_1 = self.env['social.media'].create({
            'name': 'Social media: T demo'
        })
