/** @odoo-module */

import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { formatDateTime } from "@web/core/l10n/dates";
import { SocialPostCommentEmoji } from "../social_post_comment_emojis/social_post_comment_emojis";
import { Component, useState } from "@odoo/owl";

const { DateTime } = luxon;

export class SocialPostComment extends Component {
    static components = { SocialPostCommentEmoji };
    static template = 'viin_social.SocialPostComment';
    static props = {
        comment: { type: Object, optional: true },
        post_id: { type: Number, optional: true },
        page_image: { type: [String, { value: false }], optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.state = useState({
            reply_comments: [],
        });
        this.props.reply_comments = [];
        this.notificationService = useService("notification");
    }

    formatLocalDateTime(value) {
        if (!value) {
            return "";
        }
        const dt = DateTime.fromSQL(value, { zone: "local" });
        return dt.isValid ? formatDateTime(dt) : value;
    }

    async _likeComment(ev) {
        ev.preventDefault();
        var target = ev.currentTarget;
        var current_comment = target.closest(".social_comment");
        var div_like_count = current_comment.querySelector(".comment_like_count");
        var social_comment_id = current_comment.getAttribute("social_comment_id");
        this.orm
            .call("social.post", "like_comment", [this.props.post_id, social_comment_id], {})
            .then((data) => {
                if (data) {
                    var new_like_count = parseInt(div_like_count.textContent) + parseInt(data);
                    div_like_count.textContent = new_like_count;
                }
            });
    }

    async _hideCommnet(ev) {
        ev.preventDefault();
        var self = this;
        var target = ev.currentTarget;
        var current_comment = target.closest(".social_comment");
        var social_comment_id = current_comment.getAttribute("social_comment_id");

        this.orm
            .call("social.post", "hide_comment", [this.props.post_id, social_comment_id], {})
            .then((data) => {
                if (data.success) {
                    current_comment.style.opacity = "0.5";
                    var buttonLike = current_comment.querySelector(".button_like_comment");
                    if (buttonLike) buttonLike.style.display = "none";
                    var buttonReply = current_comment.querySelector(".button_reply_comment");
                    if (buttonReply) buttonReply.style.display = "none";
                    var commentAction = current_comment.querySelector(".social_comment_action");
                    if (commentAction) commentAction.style.display = "none";
                    var buttonUnhide = current_comment.querySelector(".button_unhide_comment");
                    if (buttonUnhide) buttonUnhide.style.display = "inline-block";
                } else {
                    self.notificationService.add(data.msg_error, {
                        title: _t("Error"),
                        type: "danger",
                    });
                }
            });
    }

    async _unhideComment(ev) {
        ev.preventDefault();
        var self = this;
        var target = ev.currentTarget;
        var current_comment = target.closest(".social_comment");
        var social_comment_id = current_comment.getAttribute("social_comment_id");

        this.orm
            .call("social.post", "unhide_comment", [this.props.post_id, social_comment_id], {})
            .then((data) => {
                if (data.success) {
                    current_comment.style.opacity = "1";
                    var buttonLike = current_comment.querySelector(".button_like_comment");
                    if (buttonLike) buttonLike.style.display = "inline-block";
                    var buttonReply = current_comment.querySelector(".button_reply_comment");
                    if (buttonReply) buttonReply.style.display = "inline-block";
                    var commentAction = current_comment.querySelector(".social_comment_action");
                    if (commentAction) commentAction.style.display = "inline-block";
                    var buttonUnhide = current_comment.querySelector(".button_unhide_comment");
                    if (buttonUnhide) buttonUnhide.style.display = "none";
                } else {
                    self.notificationService.add(data.msg_error, {
                        title: _t("Error"),
                        type: "danger",
                    });
                }
            });
    }

    async _deleteComment(ev) {
        ev.preventDefault();
        var target = ev.currentTarget;
        var current_comment = target.closest(".social_comment");
        var social_comment_id = current_comment.getAttribute("social_comment_id");
        var div_post_comment_count = document.querySelector(".post_comment_count");
        this.orm
            .call("social.post", "delete_comment", [this.props.post_id, social_comment_id], {})
            .then((data) => {
                if (data) {
                    current_comment.remove();
                    if (div_post_comment_count) {
                        var new_comment_count = parseInt(div_post_comment_count.textContent) - 1;
                        if (new_comment_count > 0) {
                            div_post_comment_count.textContent = new_comment_count;
                        }
                    }
                }
            });
    }

    async _showReplyInput(ev) {
        ev.preventDefault();
        var target = ev.currentTarget;
        var div_root_comment = target.closest(".social_root_comment");
        var reply_content = div_root_comment.querySelector(".social_reply_comment_input");
        var hide_divs = div_root_comment.querySelectorAll(".d-none");
        hide_divs.forEach((div) => div.classList.remove("d-none"));
        var textarea = reply_content.querySelector("textarea");
        if (textarea) textarea.focus();
    }

    async _showReplyComment(ev) {
        ev.preventDefault();
        var target = ev.currentTarget;
        target.style.display = "none";
        this.orm
            .call(
                "social.post",
                "get_reply_comments",
                [this.props.post_id, this.props.comment.id],
                {}
            )
            .then((data) => {
                this.props.reply_comments = data.replys;
                this.state.reply_comments = data.replys;
            });
    }

    async _replyComment(ev) {
        if (ev.keyCode == 13 || ev.which == 13) {
            if (!ev.shiftKey) {
                ev.preventDefault();
                var target = ev.currentTarget;
                var reply_message = target.value;
                if (reply_message == "") {
                    return;
                }
                target.value = "";
                this.orm
                    .call(
                        "social.post",
                        "add_comment",
                        [this.props.post_id, reply_message, this.props.comment.id],
                        {}
                    )
                    .then((data) => {
                        if (data) {
                            var old_comments = this.state.reply_comments;
                            var new_comments = old_comments.concat(data.replys);
                            this.state.reply_comments = new_comments;
                        }
                    });
            }
        }
    }
}
