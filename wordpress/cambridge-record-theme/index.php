<?php
/**
 * Fallback template — plain pages and posts (e.g. the AI Constitution page),
 * archives, and 404s.
 */
get_header();
?>
<div class="wrap">
    <?php if ( have_posts() ) : ?>
        <?php while ( have_posts() ) : the_post(); ?>
            <article <?php post_class( 'entry' ); ?>>
                <?php if ( is_singular() ) : ?>
                    <h1><?php the_title(); ?></h1>
                <?php else : ?>
                    <h2><a href="<?php the_permalink(); ?>"><?php the_title(); ?></a></h2>
                <?php endif; ?>
                <div class="entry-content">
                    <?php is_singular() ? the_content() : the_excerpt(); ?>
                </div>
            </article>
        <?php endwhile; ?>
        <?php the_posts_pagination(); ?>
    <?php else : ?>
        <article class="entry">
            <h1>Nothing here</h1>
            <p class="muted">That page doesn’t exist. Try the <a href="<?php echo esc_url( home_url( '/' ) ); ?>">meeting list</a> or search the transcripts.</p>
            <?php cr_theme_search_form(); ?>
        </article>
    <?php endif; ?>
</div>
<?php
get_footer();
