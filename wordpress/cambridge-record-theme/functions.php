<?php
/**
 * Cambridge Record theme.
 *
 * Page data is loaded client-side from the Cambridge Record plugin's
 * REST endpoints:
 *   /wp-json/cambridge-record/v1/meetings   — meeting list (front-page.php)
 *   /wp-json/cambridge-record/v1/search     — transcript search (search.php)
 *   /wp-json/wp/v2/meeting/{id}             — segments/votes/agenda (single-cr_meeting.php)
 *
 * No build step, no JS framework, no third-party requests.
 */

defined( 'ABSPATH' ) || exit;

define( 'CR_THEME_VERSION', '0.2.0' );


// ═══════════════════════════════════════════════════════
// 1. THEME SUPPORT
// ═══════════════════════════════════════════════════════

add_action( 'after_setup_theme', function () {
    add_theme_support( 'title-tag' );
    add_theme_support( 'html5', [ 'search-form', 'script', 'style' ] );
    register_nav_menus( [ 'primary' => 'Primary navigation' ] );
} );


// ═══════════════════════════════════════════════════════
// 2. ASSETS
//    common.js is shared; each template gets one page script.
//    CR_CONFIG gives the scripts the REST root and, for
//    logged-in editors, a nonce so draft previews load.
// ═══════════════════════════════════════════════════════

add_action( 'wp_enqueue_scripts', function () {
    $uri = get_template_directory_uri();

    wp_enqueue_style( 'cambridge-record', get_stylesheet_uri(), [], CR_THEME_VERSION );

    wp_register_script( 'cr-common', "$uri/assets/js/common.js", [], CR_THEME_VERSION, [ 'strategy' => 'defer' ] );
    wp_add_inline_script( 'cr-common', 'window.CR_CONFIG = ' . wp_json_encode( [
        'restRoot' => esc_url_raw( rest_url() ),
        'nonce'    => is_user_logged_in() ? wp_create_nonce( 'wp_rest' ) : '',
        'homeUrl'  => esc_url_raw( home_url( '/' ) ),
        'siteName' => get_bloginfo( 'name' ),
    ] ) . ';', 'before' );

    $page_script = null;
    if ( is_singular( 'cr_meeting' ) ) {
        $page_script = 'meeting';
    } elseif ( cr_theme_is_search_view() ) {
        $page_script = 'search';
    } elseif ( is_front_page() || is_post_type_archive( 'cr_meeting' ) ) {
        $page_script = 'meetings';
    }

    if ( $page_script ) {
        wp_enqueue_script( "cr-$page_script", "$uri/assets/js/$page_script.js", [ 'cr-common' ], CR_THEME_VERSION, [ 'strategy' => 'defer' ] );
    }
} );


// ═══════════════════════════════════════════════════════
// 3. SEARCH
//    search.php renders the transcript search UI and fetches
//    results from the plugin endpoint, so skip WordPress's own
//    main search query — its results would never be shown.
//
//    WordPress only treats non-empty ?s= as a search, so route
//    a bare /?s= (the "Search" nav link) to search.php as well.
// ═══════════════════════════════════════════════════════

function cr_theme_is_search_view() {
    return is_search() || isset( $_GET['s'] );
}

add_filter( 'document_title_parts', function ( $parts ) {
    if ( cr_theme_is_search_view() ) {
        $q = get_search_query();
        $parts['title'] = $q ? sprintf( '“%s” — Transcript search', $q ) : 'Transcript search';
    }
    return $parts;
} );

add_filter( 'template_include', function ( $template ) {
    if ( ! is_search() && isset( $_GET['s'] ) ) {
        return locate_template( 'search.php' ) ?: $template;
    }
    return $template;
} );

add_filter( 'posts_search', function ( $search, $query ) {
    if ( $query->is_main_query() && $query->is_search() && ! is_admin() ) {
        return ' AND 1=0 ';
    }
    return $search;
}, 10, 2 );


// ═══════════════════════════════════════════════════════
// 4. TEMPLATE HELPERS
// ═══════════════════════════════════════════════════════

/** True when the Cambridge Record plugin is active. */
function cr_theme_plugin_active() {
    return function_exists( 'cr_search_segments' );
}

/** Admin-only notice when the plugin is missing; residents see nothing. */
function cr_theme_plugin_notice() {
    if ( cr_theme_plugin_active() || ! current_user_can( 'activate_plugins' ) ) {
        return;
    }
    echo '<p class="status status--error">The Cambridge Record plugin is not active. '
       . 'This theme reads all meeting data from it — activate it under Plugins.</p>';
}

/** Format a YYYY-MM-DD meta value as "Tuesday, September 15, 2026". */
function cr_theme_format_date( $ymd, $format = 'l, F j, Y' ) {
    $date = DateTime::createFromFormat( '!Y-m-d', (string) $ymd );
    return $date ? $date->format( $format ) : '';
}

/** The transcript search form, used in the header, front page, and search page. */
function cr_theme_search_form( $size = '' ) {
    $id = 'cr-search-' . wp_unique_id();
    ?>
    <form role="search" method="get" action="<?php echo esc_url( home_url( '/' ) ); ?>" class="cr-search-form">
        <label for="<?php echo esc_attr( $id ); ?>" class="screen-reader-text">Search meeting transcripts</label>
        <div class="field <?php echo $size ? 'field--' . esc_attr( $size ) : ''; ?>">
            <input type="search" id="<?php echo esc_attr( $id ); ?>" name="s"
                   value="<?php echo esc_attr( get_search_query() ); ?>"
                   placeholder="<?php echo $size === 'lg' ? 'Search every word said — e.g. “transportation”' : 'Search transcripts'; ?>"
                   autocomplete="off" required minlength="2">
            <button type="submit">Search</button>
        </div>
    </form>
    <?php
}

/** Fallback primary nav when no menu is assigned. */
function cr_theme_default_menu() {
    echo '<ul>';
    printf( '<li><a href="%s">Meetings</a></li>', esc_url( home_url( '/' ) ) );
    printf( '<li><a href="%s">Search</a></li>', esc_url( home_url( '/?s=' ) ) );
    echo '</ul>';
}
