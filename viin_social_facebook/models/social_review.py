import requests
import datetime
from dateutil.parser import parse

from odoo import models, fields, _
from odoo.exceptions import AccessError

HOST = "https://graph.facebook.com"


class SocialReview(models.Model):
    _name = 'social.review'
    _description = 'Social Review'
    _order = 'review_date desc'

    review_date = fields.Datetime(string='Review Date', readonly=True)
    message = fields.Text(string='Message', readonly=True)
    page_id = fields.Many2one('social.page', string='Page', readonly=True)

    def _get_all_reivews(self, page_id, social_page_id, access_token):
        url = HOST + '/%s?fields=ratings{open_graph_story,recommendation_type,has_review} &access_token=%s' % (social_page_id, access_token)
        res = requests.get(url)
        data = res.json()
        ratings = data.get('ratings', False)
        review_list = []
        if ratings:
            reviews = ratings.get('data', [])
            for review in reviews:
                open_graph_story = review.get('open_graph_story', False)
                if open_graph_story:
                    start_time = parse(open_graph_story['start_time'])
                    review_date = datetime.datetime.combine(start_time.date(), start_time.time())
                    review_list.append({
                        'review_date': review_date,
                        'message': open_graph_story['message'],
                        'page_id': page_id
                    })
        self._synchronize_all_reviews(review_list, page_id)

    def _synchronize_all_reviews(self, review_list, page_id):
        if not self.env.user.has_group('viin_social.viin_social_group_editor'):
            return AccessError(_("You do not have permission to sync reviews."))
        self.search([('page_id', '=', page_id)]).sudo().unlink()
        self.sudo().create(review_list)
