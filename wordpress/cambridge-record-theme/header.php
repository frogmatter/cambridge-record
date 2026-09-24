<!doctype html>
<html <?php language_attributes(); ?>>
<head>
    <meta charset="<?php bloginfo( 'charset' ); ?>">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <?php wp_head(); ?>
</head>
<body <?php body_class(); ?>>
<?php wp_body_open(); ?>
<a class="skip-link screen-reader-text" href="#main">Skip to content</a>

<header class="site-header">
    <div class="wrap">
        <a class="site-title" href="<?php echo esc_url( home_url( '/' ) ); ?>">
            <span class="dot" aria-hidden="true"></span><?php bloginfo( 'name' ); ?>
        </a>

        <nav class="site-nav" aria-label="Primary">
            <?php
            wp_nav_menu( [
                'theme_location' => 'primary',
                'container'      => false,
                'depth'          => 1,
                'fallback_cb'    => 'cr_theme_default_menu',
            ] );
            ?>
        </nav>

        <?php if ( ! cr_theme_is_search_view() && ! is_front_page() ) : ?>
            <div class="header-search"><?php cr_theme_search_form(); ?></div>
        <?php endif; ?>
    </div>
</header>

<main id="main" class="site-main">
