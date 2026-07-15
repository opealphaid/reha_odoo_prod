/** @odoo-module */

import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { PostAttachmentsCarousel } from "../post_attachments_carousel/post_attachments_carousel";
import { SocialPostCommentEmoji } from "../social_post_comment_emojis/social_post_comment_emojis";
import { SocialPostComment } from "../social_post_comment/social_post_comment";
import { Component, useState } from "@odoo/owl";

export class SocialPostDialog extends Component {
    static components = { Dialog, SocialPostComment, SocialPostCommentEmoji };
    static template = 'viin_social.SocialPostDialog';
    static props = {
        title: { type: String, optional: true },
        post_id: { type: Number, optional: true },
        page_name: { type: String, optional: true },
        page_image: { type: String, optional: true },
        post_message: { type: String, optional: true },
        post_like_count: { type: Number, optional: true },
        post_comment_count: { type: Number, optional: true },
        first_level_comment_count: { type: Number, optional: true },
        post_share_count: { type: Number, optional: true },
        social_media_name: { type: String, optional: true },
        post_images: { type: Array, optional: true },
        attachments: { type: Array, optional: true },
        attachment_link: { type: [String, { value: false }], optional: true },
        attachment_link_title: { type: [String, { value: false }], optional: true },
        media: { type: [Object, String], optional: true },
        comments: { type: Array, optional: true },
        state: { type: String, optional: true },
        post_engagement: { type: Object, optional: true },
        hide_comments: { type: Array, optional: true },
        close: { type: Function, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.state = useState({
            comments: this.props.comments,
        });
    }

    async _showMoreComment(ev) {
        ev.preventDefault();
        var props = this.props;
        if (props.hide_comments) {
            var old_comments = props.comments;
            var new_comments = props.hide_comments.slice(0, 5);
            var comments = old_comments.concat(new_comments);
            this.state.comments = comments;
            this.props.comments = comments;
            var hide_comments = props.hide_comments.slice(6, props.hide_comments.length);
            this.props.hide_comments = hide_comments;
            if (this.props.hide_comments.length == 0) {
                var buttonShowMore = document.querySelector(".button_show_more_comment");
                if (buttonShowMore) buttonShowMore.style.display = "none";
            }
        }
    }

    async _addComment(ev) {
        if (ev.keyCode == 13 || ev.which == 13) {
            if (!ev.shiftKey) {
                ev.preventDefault();
                var target = ev.currentTarget;
                var comment_message = target.value;
                if (comment_message == "") {
                    return;
                }
                target.value = "";
                this.orm
                    .call("social.post", "add_comment", [this.props.post_id, comment_message], {})
                    .then((data) => {
                        if (data) {
                            var old_comments = this.props.comments;
                            var new_comment = data.comments.concat(old_comments);
                            this.props.comments = new_comment;
                            this.state.comments = new_comment;
                        }
                    });
            }
        }
    }

    _showMoreAttachments(ev) {
        var target = ev.currentTarget;
        var active_position = target.getAttribute("data-attachment-position");
        this.dialog.add(PostAttachmentsCarousel, {
            title: _t("Post Attachments"),
            attachments: this.props.attachments,
            active_position: active_position,
        });
    }
}
