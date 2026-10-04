<?php
/**
 * One subcommittee — /subcommittee/{slug}/
 * Rendered here from the plugin's cr_subcommittee_members() and
 * cr_body_meetings(): its description (the post content, written in WP
 * admin), current members, and the meetings it has held.
 */
get_header();

while ( have_posts() ) :
    the_post();
    $id       = get_the_ID();
    $body     = get_post_meta( $id, 'meeting_body', true );
    $members  = function_exists( 'cr_subcommittee_members' ) ? cr_subcommittee_members( $body ) : [];
    $meetings = function_exists( 'cr_body_meetings' ) ? cr_body_meetings( $body ) : [];
    ?>
    <div class="wrap">
        <?php cr_theme_plugin_notice(); ?>

        <header class="official-head measure">
            <p class="eyebrow"><a href="<?php echo esc_url( get_post_type_archive_link( 'cr_subcommittee' ) ); ?>">Subcommittees</a></p>
            <h1><?php the_title(); ?></h1>
            <div class="meta-line">
                <span><?php echo count( $meetings ); ?> recorded meeting<?php echo count( $meetings ) === 1 ? '' : 's'; ?></span>
                <?php if ( $meetings ) : ?>
                    <span>Latest <?php echo esc_html( cr_theme_format_date( $meetings[0]['meeting_date'], 'F j, Y' ) ); ?></span>
                <?php endif; ?>
            </div>
            <?php if ( trim( get_the_content() ) ) : ?>
                <div class="entry-content subcommittee-charge"><?php the_content(); ?></div>
            <?php endif; ?>
            <?php if ( $meetings ) : ?>
                <div class="subcommittee-search"><?php cr_theme_search_form( '', $body ); ?></div>
            <?php endif; ?>
        </header>

        <section aria-labelledby="members-heading">
            <h2 id="members-heading" class="official-group">Members</h2>
            <?php if ( $members ) : ?>
                <ul class="meeting-list official-list">
                    <?php foreach ( $members as $m ) : ?>
                        <li class="official-row">
                            <div class="official-row__title"><?php echo esc_html( $m['role'] ); ?></div>
                            <h3 class="official-row__name"><a href="<?php echo esc_url( $m['permalink'] ); ?>"><?php echo esc_html( $m['name'] ); ?></a></h3>
                            <div class="official-row__meta"><?php echo esc_html( $m['title'] ); ?></div>
                        </li>
                    <?php endforeach; ?>
                </ul>
            <?php else : ?>
                <p class="status">No members are listed for this subcommittee.</p>
            <?php endif; ?>
        </section>

        <section aria-labelledby="sc-meetings-heading">
            <h2 id="sc-meetings-heading" class="official-group">Meetings</h2>
            <?php if ( $meetings ) : ?>
                <ul class="meeting-list official-list">
                    <?php array_map( 'cr_theme_meeting_row', $meetings ); ?>
                </ul>
            <?php else : ?>
                <p class="status">No recorded meetings yet.</p>
            <?php endif; ?>
        </section>
    </div>
    <?php
endwhile;

get_footer();
