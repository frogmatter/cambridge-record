<?php
/**
 * Subcommittees — /subcommittees/
 * One row per cr_subcommittee post (A–Z, see functions.php), with its
 * chairs and its most recent recorded meeting.
 */
get_header();
?>
<div class="wrap">
    <?php cr_theme_plugin_notice(); ?>

    <section class="intro measure">
        <p class="eyebrow">Cambridge School Committee</p>
        <h1>Subcommittees</h1>
        <p class="lede">Much of the School Committee’s detailed work happens in its subcommittees. Each page lists the members and every recorded meeting, with full transcripts.</p>
    </section>

    <?php if ( have_posts() ) : ?>
        <ul class="meeting-list official-list">
            <?php
            while ( have_posts() ) :
                the_post();
                $body     = get_post_meta( get_the_ID(), 'meeting_body', true );
                $members  = function_exists( 'cr_subcommittee_members' ) ? cr_subcommittee_members( $body ) : [];
                $meetings = function_exists( 'cr_body_meetings' ) ? cr_body_meetings( $body ) : [];
                $chairs   = array_filter( $members, fn( $m ) => $m['role'] !== 'Member' );
                ?>
                <li class="official-row">
                    <div class="official-row__title"><?php echo count( $meetings ); ?> meeting<?php echo count( $meetings ) === 1 ? '' : 's'; ?></div>
                    <h3 class="official-row__name"><a href="<?php the_permalink(); ?>"><?php the_title(); ?></a></h3>
                    <div class="official-row__meta">
                        <?php
                        echo esc_html( implode( '; ', array_map( fn( $m ) => "{$m['role']}: {$m['name']}", $chairs ) ) ?: count( $members ) . ' members' );
                        if ( $meetings ) {
                            echo ' <span class="muted">· latest ' . esc_html( cr_theme_format_date( $meetings[0]['meeting_date'], 'M j, Y' ) ) . '</span>';
                        }
                        ?>
                    </div>
                </li>
            <?php endwhile; ?>
        </ul>
    <?php else : ?>
        <p class="status">No subcommittees have been published yet.</p>
    <?php endif; ?>
</div>
<?php
get_footer();
