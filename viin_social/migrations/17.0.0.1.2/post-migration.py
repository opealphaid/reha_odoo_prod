from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    # Update res_id in ir.attachment for social.article
    _sql = """
        UPDATE ir_attachment ia
        SET res_id = rel.social_article_id
        FROM social_article_ir_attachment_image_rel rel
        WHERE ia.id = rel.ir_attachment_id
        AND ia.res_model = 'social.article'
        AND ia.res_id != rel.social_article_id;
    """
    env.cr.execute(_sql)

    # Update res_id in ir.attachment for social.post
    domain = [('article_id', '!=', False), ('attachment_type', '=', 'file')]
    social_post_ids = env['social.post'].with_context(active_test=False).search(domain)
    for post in social_post_ids:
        if post.article_id.attachment_ids:
            post_attachment_ids = set(post.attachment_ids.ids)
            article_attachment_ids = set(post.article_id.attachment_ids.ids)

            if post_attachment_ids == article_attachment_ids:
                new_attachment_ids = post.article_id.attachment_ids.mapped(
                    lambda att: att.copy({'res_id': post.id, 'res_model': 'social.post'}).id)
                post.write({'attachment_ids': [(6, 0, new_attachment_ids)]})
