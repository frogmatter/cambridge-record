<?php
/**
 * Front page — meeting list.
 * Rows are rendered by assets/js/meetings.js from
 * /wp-json/cambridge-record/v1/meetings.
 */
get_header();
?>
<div class="wrap">
    <?php cr_theme_plugin_notice(); ?>

    <section class="intro measure">
        <p class="eyebrow">Cambridge School Committee</p>
        <h1>Every meeting, every word, searchable.</h1>
        <p class="lede">Full transcripts of Cambridge School Committee meetings, linked to the moment in the video where each word was said.</p>
        <?php cr_theme_search_form( 'lg' ); ?>
    </section>

    <section aria-labelledby="meetings-heading">
        <div class="list-toolbar">
            <h2 id="meetings-heading">Meetings</h2>
            <label for="meeting-body" class="screen-reader-text">Committee or subcommittee</label>
            <select id="meeting-body" hidden></select>
            <label for="meeting-year" class="screen-reader-text">School year</label>
            <select id="meeting-year" hidden></select>
            <label for="meeting-filter" class="screen-reader-text">Filter meetings</label>
            <div class="field"><input type="search" id="meeting-filter" placeholder="Filter by title, topic or date" autocomplete="off"></div>
        </div>

        <div id="meeting-list" aria-live="polite">
            <p class="status loading">Loading meetings</p>
        </div>
        <noscript><p class="status">The meeting list needs JavaScript. You can still search transcripts with the form above.</p></noscript>
    </section>
</div>
<?php
get_footer();
