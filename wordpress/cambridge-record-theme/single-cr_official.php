<?php
/**
 * One official — profile + voting record.
 * The header is rendered here from post meta; the voting record is loaded
 * by assets/js/official.js from /wp-json/cambridge-record/v1/officials/{id}.
 */
get_header();

while ( have_posts() ) :
    the_post();
    $id            = get_the_ID();
    $title         = get_post_meta( $id, 'official_title', true ) ?: 'Member';
    $term_start    = get_post_meta( $id, 'term_start', true );
    $term_end      = get_post_meta( $id, 'term_end', true );
    $is_voting     = (bool) get_post_meta( $id, 'is_voting_member', true );
    $subcommittees = json_decode( get_post_meta( $id, 'subcommittees_json', true ) ?: '[]', true ) ?: [];
    ?>
    <div class="wrap">
        <?php cr_theme_plugin_notice(); ?>

        <header class="official-head measure">
            <p class="eyebrow"><a href="<?php echo esc_url( get_post_type_archive_link( 'cr_official' ) ); ?>">Officials</a></p>
            <h1><?php the_title(); ?></h1>
            <div class="meta-line">
                <span><?php echo esc_html( $title ); ?><?php echo $is_voting ? '' : ' (non-voting)'; ?></span>
                <?php if ( $term_start ) : ?>
                    <span>Term <?php echo esc_html( cr_theme_format_date( $term_start, 'M Y' ) ); ?> – <?php echo esc_html( $term_end ? cr_theme_format_date( $term_end, 'M Y' ) : 'present' ); ?></span>
                <?php endif; ?>
            </div>
            <?php if ( $subcommittees ) : ?>
                <ul class="subcommittees">
                    <?php foreach ( $subcommittees as $sc ) : ?>
                        <?php $page = function_exists( 'cr_find_subcommittee' ) ? cr_find_subcommittee( $sc['body'] ?? null ) : null; ?>
                        <li><?php if ( $page ) : ?><a href="<?php echo esc_url( get_permalink( $page ) ); ?>"><?php endif; ?><?php echo esc_html( $sc['name'] ); ?><?php if ( $page ) : ?></a><?php endif; ?><?php echo ( $sc['role'] ?? 'Member' ) !== 'Member' ? ' <span class="muted">· ' . esc_html( $sc['role'] ) . '</span>' : ''; ?></li>
                    <?php endforeach; ?>
                </ul>
            <?php endif; ?>
        </header>

        <?php if ( $is_voting ) : ?>
            <section class="record" id="record" data-id="<?php echo (int) $id; ?>" aria-labelledby="record-heading">
                <div class="list-toolbar">
                    <h2 id="record-heading">Voting record</h2>
                    <label class="check"><input type="checkbox" id="only-dissents"> Only votes against the majority</label>
                    <label class="check"><input type="checkbox" id="show-procedural"> Include procedural votes</label>
                    <label for="record-filter" class="screen-reader-text">Filter votes</label>
                    <div class="field"><input type="search" id="record-filter" placeholder="Filter votes" autocomplete="off"></div>
                </div>
                <p class="record-summary" id="record-summary" aria-live="polite"></p>
                <div id="record-list"><p class="status loading">Loading votes</p></div>
                <noscript><p class="status">The voting record needs JavaScript.</p></noscript>
            </section>
        <?php else : ?>
            <p class="status">Student members don’t cast roll-call votes, so there’s no voting record.</p>
        <?php endif; ?>
    </div>
    <?php
endwhile;

get_footer();
