<?php
/**
 * Review times — Meetings → Review times (WP admin).
 *
 * The pipeline places each official vote and agenda item on the video by
 * matching captions (match_agenda.py). Some matches are weak or missing.
 * This screen lists those for a person to check against the video.
 *
 * Decisions are stored in the meeting's review_json meta, keyed by each
 * item's stable `key` (written by enrich_meetings.py), and applied to
 * votes_json / agenda_json right away. enrich_meetings.py re-applies them
 * after every run, so re-running the pipeline never undoes a review.
 *
 *   review_json = { "votes":  { key: {status, start_seconds, by, at} },
 *                   "agenda": { key: {…} } }
 *   status: 'confirmed' (time is right) | 'corrected' (time set by hand)
 *           | 'cleared' (not in the video)
 */

defined( 'ABSPATH' ) || exit;

const CR_REVIEW_THRESHOLD = 0.7;   // votes placed with a lower match_score need a look


// ── Data helpers ─────────────────────────────────────

function cr_seek_url( $embed_url, $seconds ) {
    if ( ! $embed_url || $seconds === null ) {
        return null;
    }
    $url = remove_query_arg( [ 't', 'seek' ], $embed_url );
    return add_query_arg( 'seek', (int) $seconds, $url );
}

/** What a vote or agenda item is about, for the review list. */
function cr_review_label( array $item, $kind ) {
    if ( $kind === 'agenda' ) {
        return trim( ( ! empty( $item['docket'] ) ? '#' . $item['docket'] . ' ' : '' ) . ( $item['title'] ?? '' ) );
    }
    $items = $item['items'] ?? [];
    if ( count( $items ) === 1 && ! empty( $items[0]['title'] ) ) {
        return trim( ( $items[0]['docket'] ? '#' . $items[0]['docket'] . ' ' : '' ) . $items[0]['title'] );
    }
    if ( count( $items ) > 1 ) {
        return count( $items ) . ' items: #' . implode( ', #', array_column( $items, 'docket' ) );
    }
    return ucfirst( (string) ( $item['motion_text'] ?? 'Vote' ) );
}

function cr_get_review( $meeting_id ) {
    $review = json_decode( get_post_meta( $meeting_id, 'review_json', true ) ?: '{}', true );
    return [
        'votes'  => $review['votes'] ?? [],
        'agenda' => $review['agenda'] ?? [],
    ];
}

/** Does this vote/agenda item need a person to look at it? */
function cr_needs_review( array $item, $kind, array $decision = null ) {
    if ( $decision ) {
        return false;
    }
    if ( $kind === 'vote' ) {
        return ( $item['source'] ?? '' ) === 'minutes'
            && ( $item['start_seconds'] === null || (float) ( $item['match_score'] ?? 0 ) < CR_REVIEW_THRESHOLD );
    }
    return ! empty( $item['docket'] ) && ( $item['start_seconds'] ?? null ) === null;
}

/**
 * Review rows for one meeting. $all = every official vote and docketed item,
 * not just the ones that need review.
 */
function cr_review_items( $meeting_id, $all = false ) {
    $votes  = json_decode( get_post_meta( $meeting_id, 'votes_json', true ) ?: '[]', true ) ?: [];
    $agenda = json_decode( get_post_meta( $meeting_id, 'agenda_json', true ) ?: '[]', true ) ?: [];
    $review = cr_get_review( $meeting_id );
    $rows   = [];

    $placed = array_values( array_filter( $votes, fn( $v ) => ( $v['start_seconds'] ?? null ) !== null ) );

    foreach ( $votes as $v ) {
        if ( ( $v['source'] ?? '' ) !== 'minutes' || empty( $v['key'] ) ) {
            continue;
        }
        $decision = $review['votes'][ $v['key'] ] ?? null;
        $needs = cr_needs_review( $v, 'vote', $decision );
        if ( ! $all && ! $needs ) {
            continue;
        }
        // Where to start looking: after the previous placed vote, before the next one
        $prev = $next = null;
        foreach ( $placed as $p ) {
            if ( $p['index'] < $v['index'] ) { $prev = $p; }
            if ( $p['index'] > $v['index'] && ! $next ) { $next = $p; }
        }
        $rows[] = [
            'kind'          => 'vote',
            'key'           => $v['key'],
            'label'         => cr_review_label( $v, 'vote' ),
            'motion_text'   => $v['motion_text'] ?? '',
            'section'       => $v['section_title'] ?? null,
            'result'        => $v['result'] ?? '',
            'tally'         => isset( $v['vote_for'] ) ? $v['vote_for'] . '–' . $v['vote_against'] : null,
            'roll_call'     => $v['roll_call'] ?? [],
            'start_seconds' => $v['start_seconds'] ?? null,
            'match_score'   => $v['match_score'] ?? null,
            'match_method'  => $v['match_method'] ?? null,
            'needs_review'  => $needs,
            'decision'      => $decision,
            'after_seconds' => $prev ? ( $prev['end_seconds'] ?? $prev['start_seconds'] ) : null,
            'before_seconds'=> $next ? $next['start_seconds'] : null,
        ];
    }

    foreach ( $agenda as $a ) {
        if ( empty( $a['key'] ) || empty( $a['docket'] ) ) {
            continue;
        }
        $decision = $review['agenda'][ $a['key'] ] ?? null;
        $needs = cr_needs_review( $a, 'agenda', $decision );
        if ( ! $all && ! $needs ) {
            continue;
        }
        $rows[] = [
            'kind'          => 'agenda',
            'key'           => $a['key'],
            'label'         => cr_review_label( $a, 'agenda' ),
            'section'       => $a['section'] ?? null,
            'start_seconds' => $a['start_seconds'] ?? null,
            'match_method'  => $a['match_method'] ?? null,
            'needs_review'  => $needs,
            'decision'      => $decision,
        ];
    }
    return $rows;
}


// ── REST: read the queue, save a decision ─────────────

add_action( 'rest_api_init', function () {
    register_rest_route( 'cambridge-record/v1', '/review', [
        [
            'methods'             => 'GET',
            'callback'            => 'cr_review_get',
            'permission_callback' => fn() => current_user_can( 'edit_posts' ),
        ],
        [
            'methods'             => 'POST',
            'callback'            => 'cr_review_save',
            'permission_callback' => fn( $r ) => current_user_can( 'edit_post', (int) $r['meeting_id'] ),
            'args'                => [
                'meeting_id'    => [ 'required' => true, 'sanitize_callback' => 'absint' ],
                'kind'          => [ 'required' => true, 'enum' => [ 'vote', 'agenda' ] ],
                'key'           => [ 'required' => true, 'type' => 'string' ],
                'action'        => [ 'required' => true, 'enum' => [ 'confirm', 'set', 'clear', 'reset' ] ],
                'start_seconds' => [ 'type' => 'number' ],
            ],
        ],
    ] );
} );

/**
 * GET /review                → every meeting with its counts, plus all rows needing review
 * GET /review?meeting=ID     → that meeting's rows (add &all=1 for every vote and item)
 */
function cr_review_get( WP_REST_Request $request ) {
    $only = (int) $request->get_param( 'meeting' );
    $all  = (bool) $request->get_param( 'all' );

    $meetings = get_posts( [
        'post_type'      => 'cr_meeting',
        'post_status'    => [ 'publish', 'draft', 'pending', 'private' ],
        'posts_per_page' => -1,
        'orderby'        => 'meta_value',
        'meta_key'       => 'meeting_date',
        'order'          => 'DESC',
    ] );

    $out_meetings = [];
    $out_items    = [];
    foreach ( $meetings as $m ) {
        $every = cr_review_items( $m->ID, true );
        $out_meetings[] = [
            'id'        => $m->ID,
            'title'     => get_the_title( $m->ID ),
            'date'      => get_post_meta( $m->ID, 'meeting_date', true ),
            'status'    => $m->post_status,
            'embed_url' => get_post_meta( $m->ID, 'cablecast_embed_url', true ),
            'view_url'  => get_permalink( $m->ID ),
            'needs'     => count( array_filter( $every, fn( $r ) => $r['needs_review'] ) ),
            'reviewed'  => count( array_filter( $every, fn( $r ) => $r['decision'] ) ),
            'total'     => count( $every ),
        ];
        if ( $only && $only !== $m->ID ) {
            continue;
        }
        $rows = $only && $all ? $every : array_values( array_filter( $every, fn( $r ) => $r['needs_review'] || ( $only && $r['decision'] ) ) );
        foreach ( $rows as $r ) {
            $out_items[] = [ 'meeting_id' => $m->ID ] + $r;
        }
    }
    return rest_ensure_response( [ 'threshold' => CR_REVIEW_THRESHOLD, 'meetings' => $out_meetings, 'items' => $out_items ] );
}

/** Save one decision and apply it to votes_json / agenda_json. */
function cr_review_save( WP_REST_Request $request ) {
    $meeting_id = (int) $request['meeting_id'];
    $kind       = $request['kind'];
    $key        = (string) $request['key'];
    $action     = $request['action'];

    if ( get_post_type( $meeting_id ) !== 'cr_meeting' ) {
        return new WP_Error( 'cr_not_found', 'Meeting not found', [ 'status' => 404 ] );
    }

    $field = $kind === 'vote' ? 'votes_json' : 'agenda_json';
    $list  = json_decode( get_post_meta( $meeting_id, $field, true ) ?: '[]', true ) ?: [];
    $pos   = null;
    foreach ( $list as $i => $item ) {
        if ( ( $item['key'] ?? null ) === $key ) {
            $pos = $i;
        }
    }
    if ( $pos === null ) {
        return new WP_Error( 'cr_not_found', 'Item not found — re-run enrich_meetings.py to add review keys', [ 'status' => 404 ] );
    }

    $review = cr_get_review( $meeting_id );
    $bucket = $kind === 'vote' ? 'votes' : 'agenda';
    $item   = $list[ $pos ];

    if ( $action === 'reset' ) {
        // Forget the decision and put back what the pipeline had found
        $original = $review[ $bucket ][ $key ]['original'] ?? null;
        unset( $review[ $bucket ][ $key ] );
        if ( $original ) {
            $restored = array_merge( $item, $original );
            unset( $restored['reviewed'] );
            $list[ $pos ] = $restored;
            update_post_meta( $meeting_id, $field, wp_slash( wp_json_encode( $list ) ) );
        }
    } else {
        $seconds = match ( $action ) {
            'confirm' => $item['start_seconds'] ?? null,
            'set'     => max( 0, (float) $request['start_seconds'] ),
            'clear'   => null,
        };
        if ( $action === 'confirm' && $seconds === null ) {
            return new WP_Error( 'cr_no_time', 'Nothing to confirm — this item has no time', [ 'status' => 400 ] );
        }
        // The pipeline's own values, kept from the first decision so Undo can restore them
        $original = $review[ $bucket ][ $key ]['original'] ?? array_intersect_key(
            $item, array_flip( [ 'start_seconds', 'deep_link_url', 'matched', 'match_method', 'match_score' ] )
        );
        $review[ $bucket ][ $key ] = [
            'status'        => [ 'confirm' => 'confirmed', 'set' => 'corrected', 'clear' => 'cleared' ][ $action ],
            'start_seconds' => $seconds,
            'by'            => wp_get_current_user()->user_login,
            'at'            => gmdate( 'c' ),
            'original'      => $original,
        ];
        $list[ $pos ] = cr_apply_decision( $item, $review[ $bucket ][ $key ], get_post_meta( $meeting_id, 'cablecast_embed_url', true ) );
        update_post_meta( $meeting_id, $field, wp_slash( wp_json_encode( $list ) ) );
    }

    update_post_meta( $meeting_id, 'review_json', wp_slash( wp_json_encode( $review ) ) );

    $rows = array_values( array_filter( cr_review_items( $meeting_id, true ), fn( $r ) => $r['key'] === $key && $r['kind'] === $kind ) );
    return rest_ensure_response( [ 'meeting_id' => $meeting_id ] + ( $rows[0] ?? [] ) );
}

/** Same rule as apply_review() in enrich_meetings.py. */
function cr_apply_decision( array $item, array $decision, $embed_url ) {
    $seconds = $decision['start_seconds'];
    $item['start_seconds'] = $seconds;
    $item['deep_link_url'] = cr_seek_url( $embed_url, $seconds );
    $item['matched']       = $seconds !== null;
    $item['reviewed']      = $decision['status'];
    if ( $decision['status'] !== 'confirmed' ) {
        $item['match_method'] = $decision['status'] === 'cleared' ? 'reviewed_not_in_video' : 'reviewed';
        $item['match_score']  = $seconds === null ? 0 : 1;
    }
    return $item;
}


// ── Admin page ────────────────────────────────────────

add_action( 'admin_menu', function () {
    $needs = 0;
    foreach ( get_posts( [ 'post_type' => 'cr_meeting', 'post_status' => 'any', 'posts_per_page' => -1, 'fields' => 'ids' ] ) as $id ) {
        $needs += count( cr_review_items( $id ) );
    }
    $bubble = $needs ? sprintf( ' <span class="awaiting-mod">%d</span>', $needs ) : '';
    add_submenu_page( 'edit.php?post_type=cr_meeting', 'Review times', 'Review times' . $bubble,
                      'edit_posts', 'cr-review', 'cr_render_review_page' );
} );

add_action( 'admin_enqueue_scripts', function ( $hook ) {
    if ( $hook !== 'cr_meeting_page_cr-review' ) {
        return;
    }
    $base = plugin_dir_url( dirname( __FILE__ ) );
    wp_enqueue_style( 'cr-review', $base . 'admin/review.css', [], CR_PLUGIN_VERSION );
    wp_enqueue_script( 'cr-review', $base . 'admin/review.js', [], CR_PLUGIN_VERSION, true );
    wp_localize_script( 'cr-review', 'CR_REVIEW', [
        'restRoot' => esc_url_raw( rest_url( 'cambridge-record/v1/review' ) ),
        'wpRoot'   => esc_url_raw( rest_url( 'wp/v2/meeting/' ) ),
        'nonce'    => wp_create_nonce( 'wp_rest' ),
    ] );
} );

function cr_render_review_page() {
    ?>
    <div class="wrap cr-review">
        <h1>Review times</h1>
        <p class="description">
            The pipeline places each official vote and agenda item on the video by matching the captions.
            These are the ones it couldn’t place, or placed with low confidence. Watch the moment, then
            confirm it, set the right time, or clear it if it isn’t in the video. Your decisions are kept
            when the pipeline re-runs.
        </p>
        <div class="cr-review__toolbar">
            <label>Meeting <select id="cr-meeting"><option value="">All meetings that need review</option></select></label>
            <label><input type="checkbox" id="cr-all"> Show every vote in this meeting</label>
            <span id="cr-progress" class="cr-review__progress"></span>
        </div>
        <div class="cr-review__layout">
            <div class="cr-review__list"><table class="widefat striped"><thead><tr>
                <th>Meeting</th><th>Item</th><th>Time</th><th>Status</th>
            </tr></thead><tbody id="cr-rows"><tr><td colspan="4">Loading…</td></tr></tbody></table></div>
            <div class="cr-review__panel" id="cr-panel" hidden>
                <div class="cr-review__player"><iframe id="cr-player" title="Meeting video" allow="autoplay; fullscreen"></iframe></div>
                <div class="cr-review__now">Player at <strong id="cr-now">—</strong></div>
                <h2 id="cr-item-title"></h2>
                <p id="cr-item-detail" class="description"></p>
                <div class="cr-review__actions">
                    <button type="button" class="button button-primary" id="cr-use-now">Use current time</button>
                    <button type="button" class="button" id="cr-confirm">Looks right</button>
                    <span class="cr-review__set"><input type="text" id="cr-time" placeholder="h:mm:ss" size="8"> <button type="button" class="button" id="cr-set">Set</button></span>
                    <button type="button" class="button-link cr-review__clear" id="cr-clear">Not in the video</button>
                    <button type="button" class="button-link" id="cr-reset" hidden>Undo my decision</button>
                </div>
                <p id="cr-message" class="cr-review__message" aria-live="polite"></p>
                <h3>Transcript around the player</h3>
                <div class="cr-review__transcript" id="cr-transcript"></div>
            </div>
        </div>
    </div>
    <?php
}
