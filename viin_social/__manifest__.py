{
    'name': "Social Marketing",
    'name_vi_VN': "Social Marketing",

    'summary': """
Integration and Management of social networks.""",

    'summary_vi_VN': """
Tích hợp và quản lý các Mạng xã hội
        """,

    'description': """
What it does
============
Social Marketing is a base module that provides social network management and integration features. This module builds basic models and interfaces to integrate with different social media platforms through extension modules.

Key Features
============
- Flexible Model Architecture:
    * Social Media Model: Manages connections to social media platforms
    * Social Page Model: Manages social media pages
    * Social Article Model: Manages content of posts
    * Social Post Model: Manages social media posts
    * Social Notice Model: Manages notifications from social media

- Synchronization System:
    * Automatic data synchronization via cron jobs
    * Synchronization of old posts
    * Authentication token status tracking

- Interaction Management:
    * Track metrics: views_count, likes_count, comments_count, shares_count
    * Support for diverse attachments: images, videos, files, links
    * Integration with Odoo's chat system (mail_channel)

- Detailed Access Rights:
    * Administrator: Full system administration rights
    * Approver: Content approval rights
    * Editor: Content creation and editing rights

Benefits
========
- Modular architecture allows for easy expansion
- Pre-integrated with Odoo's core features
- Support for multiple social media platforms
- Centralized management of social media interactions

Who Should Use This Module
==========================
- Developers:
    * Need a framework to develop social media integrations
    * Want to leverage Odoo's existing features
    * Need a stable platform for expansion

Notes
=====
You need to integrate two supported modules `Facebook Social Marketing <https://viindoo.com/apps/app/17.0/viin_social_facebook>`_ and `LinkedIn Social Marketing <https://viindoo.com/apps/app/17.0/viin_social_linkedin>`_ to publish and manage your social posts.

Known Issues
============
Warning: To avoid conflicts in the process of using this Social Marketing Module , you must uninstall Odoo's Social Marketing if you are using it.

Supported Editions
==================
1. Community Edition

    """,

    'description_vi_VN': """
Mô tả
=====
Social Marketing là một mô đun cơ sở cung cấp các tính năng quản lý và tích hợp mạng xã hội. Mô đun này xây dựng các model và interface cơ bản để tích hợp với các nền tảng mạng xã hội khác nhau thông qua các mô đun mở rộng.

Tính năng nổi bật
=================
- Kiến trúc Model Linh Hoạt
    * Social Media Model: Quản lý kết nối với các nền tảng mạng xã hội
    * Social Page Model: Quản lý các trang mạng xã hội
    * Social Article Model: Quản lý nội dung bài viết
    * Social Post Model: Quản lý các bài đăng trên mạng xã hội
    * Social Notice Model: Quản lý thông báo từ mạng xã hội

- Hệ thống Đồng bộ hóa
    * Cron job tự động đồng bộ dữ liệu
    * Đồng bộ bài viết cũ

- Quản lý Tương tác
    * Theo dõi số liệu: views_count, likes_count, comments_count, shares_count
    * Hỗ trợ attachment đa dạng: hình ảnh, video, file, link
    * Tích hợp với hệ thống chat của Odoo (mail_channel)

- Phân quyền Chi tiết
    * Administrator: Quyền quản trị toàn bộ hệ thống
    * Approver: Quyền phê duyệt nội dung
    * Editor: Quyền tạo và chỉnh sửa nội dung

Lợi ích
=======
- Kiến trúc module hóa cho phép dễ dàng mở rộng
- Tích hợp sẵn với các tính năng core của Odoo
- Hỗ trợ đa nền tảng mạng xã hội
- Quản lý tập trung các tương tác mạng xã hội

Ai nên sử dụng mô-đun này
=========================
- Nhà phát triển
    * Cần framework để phát triển tích hợp mạng xã hội
    * Muốn tận dụng các tính năng có sẵn của Odoo
    * Cần một nền tảng ổn định để mở rộng

Lưu ý
=====
Bạn cần cài đặt hai mô đun bổ trợ `Facebook Social Marketing <https://viindoo.com/vi/apps/app/17.0/viin_social_facebook>`_ và `LinkedIn Social Marketing <https://viindoo.com/vi/apps/app/17.0/viin_social_linkedin>`_ để có thể đăng bài và quản lý bài đăng trên trang.

Các Hạn chế đã biết
===================
Cảnh báo: Để tránh xung đột trong quá trình sử dụng Mô-đun Social Marketing này, bạn phải gỡ cài đặt Mô-đun Social Marketing của Odoo nếu bạn đang sử dụng nó.

Ấn bản được Hỗ trợ
==================
1. Ấn bản Community
    """,

    'author': "Viindoo",
    'website': "https://viindoo.com/intro/social-marketing",
    'live_test_url': "https://v17demo-int.viindoo.com",
    'live_test_url_vi_VN': "https://v17demo-vn.viindoo.com",
    'demo_video_url': "https://youtu.be/T12bsc3uquE",
    'support': "apps.support@viindoo.com",
    'category': 'Marketing/Social Marketing',
    'version': '0.1.2',

    # any module necessary for this one to work correctly
    'depends': ['mail', 'web_editor', 'to_base', 'utm'],
    # always loaded
    'data': [
        'security/social_security.xml',
        'security/ir.model.access.csv',
        'views/root_menu.xml',
        'views/social_article_views.xml',
        'views/social_post_views.xml',
        'views/social_page_views.xml',
        'views/social_media_views.xml',
        'views/social_notice_views.xml',
        'views/res_config_settings_views.xml',
        'data/social_media_data.xml',
        'data/social_page_data.xml',
        'data/social_post_data.xml',
        'wizards/social_post_action_edit_post_view.xml',
        'wizards/wizard_social_confirm.xml'
    ],
    'assets': {
        'web.assets_backend': [
            'viin_social/static/src/components/*/*',
            'viin_social/static/src/js/*',
            'viin_social/static/src/views/*/*',
            'viin_social/static/src/scss/*',
            'viin_social/static/src/core/web/store_service_patch.js',
            'viin_social/static/src/core/web/socialchat_core_web_service.js',
            'viin_social/static/src/core/web/suggestion_service_patch.js',
            'viin_social/static/src/core/public_web/discuss_app_model_patch.js',
            'viin_social/static/src/core/public_web/messaging_menu_patch.js',
            'viin_social/static/src/core/public_web/thread_model_patch.js',
            'viin_social/static/src/core/public_web/discuss_app_category_model_patch.js',
            'viin_social/static/src/core/common/*',
        ],

    },
    # only loaded in demonstration mode
    'images': [
        'static/description/main_screenshot.png'
    ],
    'installable': True,
    'application': True,
    'price': 69.93,
    'subscription_price': 9.9,
    'currency': 'EUR',
    'license': 'OPL-1',
}
