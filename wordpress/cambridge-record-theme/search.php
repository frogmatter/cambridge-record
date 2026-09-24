<?php
/**
 * Transcript search. Handles /?s=term.
 * Results are rendered by assets/js/search.js from
 * /wp-json/cambridge-record/v1/search.
 */
get_header();
?>
<div class="wrap">
    <?php cr_theme_plugin_notice(); ?>

    <section class="search-head">
        <p class="eyebrow">Search transcripts</p>
        <h1 class="screen-reader-text">Search meeting transcripts</h1>
        <?php cr_theme_search_form( 'lg' ); ?>
        <p class="search-summary" id="search-summary" aria-live="polite"></p>
    </section>

    <div id="search-results"></div>
    <noscript><p class="status">Search results need JavaScript.</p></noscript>
</div>
<?php
get_footer();
