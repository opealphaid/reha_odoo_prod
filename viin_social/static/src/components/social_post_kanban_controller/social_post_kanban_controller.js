/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { KanbanController } from "@web/views/kanban/kanban_controller";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { SocialPostDialog } from "../social_post_dialog/social_post_dialog";

patch(KanbanController.prototype, {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.dialog = useService("dialog");
    },

    async openRecord(record, mode) {
        if (record.resModel === "social.post" && record.data.state === "posted") {
            Promise.all([
                this._getPostDetailData(record),
                this._getPostEngagementData(record),
            ]).then((values) => {
                this.dialog.add(SocialPostDialog, {
                    title: _t("Social Post"),
                    post_id: values[0].post_id,
                    page_name: values[0].page_name,
                    page_image: values[0].page_image,
                    post_message: values[0].post_message,
                    post_like_count: values[1].likes_count,
                    post_comment_count: values[1].comments_count,
                    first_level_comment_count: values[0].first_level_comment_count,
                    post_share_count: values[1].shares_count,
                    social_media_name: values[0].social_media_name,
                    post_images: values[0].post_images,
                    attachments: values[0].attachments,
                    attachment_link: values[0].attachment_link,
                    attachment_link_title: values[0].attachment_link_title,
                    media: values[0].media,
                    comments: values[0].comments.slice(0, 5),
                    state: values[0].state,
                    post_engagement: values[1],
                    hide_comments: values[0].comments.slice(6, values[0].comments.length),
                });
            });
        } else {
            super.openRecord(record, mode);
        }
    },

    async _getPostDetailData(record) {
        return await this.orm.call(record.resModel, "get_post_content", [record.resId], {});
    },

    async _getPostEngagementData(record) {
        return await this.orm.call(record.resModel, "update_post_engagement", [record.resId], {});
    },
});
