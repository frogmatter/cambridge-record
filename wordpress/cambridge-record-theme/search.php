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
        <p class="search-help">Type a word or phrase. Results show every moment it was said, linked to that point in the video. Words are matched in order, so <em>special ed</em> finds “special education”. Captions are machine-generated, so if a name doesn’t turn up, try a shorter phrase or another spelling.</p>
        <div class="search-filters">
            <p class="search-summary" id="search-summary" aria-live="polite"></p>
            <label for="search-body" class="screen-reader-text">Committee or subcommittee</label>
            <select id="search-body" hidden></select>
        </div>
    </section>

    <div id="search-results"></div>
    <noscript><p class="status">Search results need JavaScript.</p></noscript>
</div>
<?php
get_footer();
