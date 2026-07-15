from odoo import models, fields


class SocialPostActionEditPost(models.TransientModel):
    _name = 'social.post.action.edit.post'
    _description = "Edit Post"

    post_id = fields.Many2one('social.post', string='Post On Social Page', required=True)
    message = fields.Text(string='New content', required=True)

    def action_confirm_edit(self):
        pass
