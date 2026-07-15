from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    posts = env['social.post'].search([])
    posts._update_attachment()
