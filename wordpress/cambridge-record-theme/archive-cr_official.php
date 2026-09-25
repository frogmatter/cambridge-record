<?php
/**
 * Officials — /officials/
 * Rendered by assets/js/officials.js from /wp-json/cambridge-record/v1/officials.
 */
get_header();
?>
<div class="wrap">
    <?php cr_theme_plugin_notice(); ?>

    <section class="intro measure">
        <p class="eyebrow">Cambridge School Committee</p>
        <h1>Officials</h1>
        <p class="lede">Every roll-call vote each member has cast, taken from the official minutes and linked to the moment in the meeting video.</p>
    </section>

    <div id="officials" aria-live="polite">
        <p class="status loading">Loading officials</p>
    </div>
    <noscript><p class="status">The officials list needs JavaScript.</p></noscript>
</div>
<?php
get_footer();
