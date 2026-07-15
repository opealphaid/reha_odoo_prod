from odoo import models
import requests

host = "https://graph.facebook.com"


class SocialPostActionEditPost(models.TransientModel):
    _inherit = 'social.post.action.edit.post'

    def action_confirm_edit(self):
        self.ensure_one()
        Post = self.post_id
        if Post.media_id.social_provider == 'facebook':
            params = {'access_token': Post.page_id.facebook_page_access_token, 'message': self.message}
            url = host + "/%s" % (Post.social_post_id)
            req = requests.post(url, params=params)
            req.raise_for_status()
            Post.write({'message': self.message})
        else:
            return super(SocialPostActionEditPost, self).action_confirm_edit()
