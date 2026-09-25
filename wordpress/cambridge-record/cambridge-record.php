<?php
/**
 * Plugin Name: Cambridge Record
 * Description: Civic meeting archive for Cambridge Public Schools.
 *              Single post per meeting — segments, agenda items, and votes
 *              stored as JSON in post meta. Designed for shared hosting.
 *              No plugin dependencies. REST API ready for the local pipeline.
 * Version:     0.2.1
 * Author:      Matt / Cambridge Public Schools
 * License:     CC BY-SA 4.0
 * Site:        mediatechaction.com
 */

defined( 'ABSPATH' ) || exit;


// ═══════════════════════════════════════════════════════
// 1. CUSTOM POST TYPES
//    Three post types only: meeting, official, issue.
//    Segments, agenda items, and votes live inside
//    meeting post meta as JSON — not as separate posts.
// ═══════════════════════════════════════════════════════

add_action( 'init', 'cr_register_post_types' );

function cr_register_post_types() {

    // ── meeting ──────────────────────────────────────
    // One post per School Committee meeting session.
    // Everything about that meeting (transcript, agenda,
    // votes) lives in this post's meta fields.
    register_post_type( 'cr_meeting', [
        'label'              => 'Meetings',
        'labels'             => cr_labels( 'Meeting', 'Meetings' ),
        'public'             => true,
        'show_in_rest'       => true,
        'rest_base'          => 'meeting',
        'supports'           => [ 'title', 'editor', 'custom-fields' ],
        'rewrite'            => [ 'slug' => 'meeting' ],
        'menu_icon'          => 'dashicons-video-alt2',
        'menu_position'      => 5,
    ] );

    // ── official ─────────────────────────────────────
    // One post per School Committee member or administrator.
    // Voting records are derived from votes_json in meetings.
    register_post_type( 'cr_official', [
        'label'              => 'Officials',
        'labels'             => cr_labels( 'Official', 'Officials' ),
        'public'             => true,
        'show_in_rest'       => true,
        'rest_base'          => 'official',
        'supports'           => [ 'title', 'thumbnail', 'custom-fields' ],
        'rewrite'            => [ 'slug' => 'official' ],
        'menu_icon'          => 'dashicons-groups',
        'menu_position'      => 6,
    ] );

    // ── issue ─────────────────────────────────────────
    // A topic tracked across multiple meetings.
    // Manually curated for the pilot; AI clustering in Phase 5.
    register_post_type( 'cr_issue', [
        'label'              => 'Issues',
        'labels'             => cr_labels( 'Issue', 'Issues' ),
        'public'             => true,
        'show_in_rest'       => true,
        'rest_base'          => 'issue',
        'supports'           => [ 'title', 'editor', 'custom-fields' ],
        'rewrite'            => [ 'slug' => 'issue' ],
        'menu_icon'          => 'dashicons-tag',
        'menu_position'      => 7,
    ] );
}

function cr_labels( $singular, $plural ) {
    return [
        'name'          => $plural,
        'singular_name' => $singular,
        'add_new_item'  => "Add New $singular",
        'edit_item'     => "Edit $singular",
        'view_item'     => "View $singular",
        'search_items'  => "Search $plural",
        'not_found'     => "No $plural found",
    ];
}


// ═══════════════════════════════════════════════════════
// 2. META FIELDS
//    All registered with show_in_rest: true so the
//    pipeline can read and write via the WP REST API.
//
//    JSON fields store arrays of objects — the pipeline
//    serialises them; WordPress stores as strings.
//    The REST API returns them as plain strings; the
//    pipeline and theme JSON.parse() them client-side.
// ═══════════════════════════════════════════════════════

add_action( 'init', 'cr_register_meta_fields' );

function cr_register_meta_fields() {

    // ── cr_meeting ────────────────────────────────────

    // Scalar fields — one value each
    $meeting_scalars = [
        'meeting_date'           => 'string',   // YYYY-MM-DD
        'meeting_body'           => 'string',   // 'Cambridge School Committee'
        'cablecast_vod_id'       => 'integer',
        'cablecast_embed_url'    => 'string',   // base VOD URL
        'agenda_url'             => 'string',   // CPS website agenda page
        'duration_seconds'       => 'integer',
        'segment_count'          => 'integer',
        'vote_count'             => 'integer',
        'agenda_item_count'      => 'integer',
        'summary'                => 'string',   // AI or extractive summary
        'summary_origin'         => 'string',   // 'ai:gemini-flash' | 'extractive' | 'pending'
        'languages_available'    => 'string',   // comma-separated
        'cr_status'              => 'string',   // 'processing' | 'ready' | 'published'
    ];
    cr_register_meta_group( 'cr_meeting', $meeting_scalars );

    // JSON blob fields — arrays of objects, stored as JSON strings.
    // Schema type is 'string' because WP stores them serialised.
    // The pipeline writes json_dumps(); the theme reads json_loads().
    $meeting_json = [
        // Array of: {index, start_seconds, end_seconds, text,
        //            speaker_label, deep_link_url, is_vote}
        'segments_json'      => 'string',

        // Array of: {item_number, title, start_seconds,
        //            end_seconds, item_type, support_doc_url,
        //            deep_link_url, matched}
        'agenda_json'        => 'string',

        // Array of: {segment_index, start_seconds, deep_link_url,
        //            motion_text, result, vote_for, vote_against,
        //            vote_abstain, voters_for, voters_against,
        //            raw_context}
        'votes_json'         => 'string',
    ];
    cr_register_meta_group( 'cr_meeting', $meeting_json );

    // ── cr_official ───────────────────────────────────
    $official_fields = [
        'full_name'         => 'string',
        'official_title'    => 'string',   // 'Chair' | 'Member' | 'Superintendent'
        'term_start'        => 'string',   // YYYY-MM-DD
        'term_end'          => 'string',   // YYYY-MM-DD or empty if current
        'is_voting_member'  => 'boolean',
    ];
    cr_register_meta_group( 'cr_official', $official_fields );

    // ── cr_issue ──────────────────────────────────────
    $issue_fields = [
        'issue_description'   => 'string',
        'first_appearance'    => 'string',   // YYYY-MM-DD
        'latest_appearance'   => 'string',   // YYYY-MM-DD
        'meeting_count'       => 'integer',
        'related_meeting_ids' => 'string',   // comma-separated WP post IDs
    ];
    cr_register_meta_group( 'cr_issue', $issue_fields );
}

function cr_register_meta_group( $post_type, array $fields ) {
    foreach ( $fields as $key => $type ) {
        register_post_meta( $post_type, $key, [
            'type'         => $type,
            'single'       => true,
            'show_in_rest' => true,
            'default'      => ( $type === 'boolean' ) ? false
                            : ( in_array( $type, ['integer','number'] ) ? 0 : '' ),
        ] );
    }
}


// ═══════════════════════════════════════════════════════
// 3. CUSTOM REST ENDPOINTS
//    /wp-json/cambridge-record/v1/search?q=...
//    Full-text search across all meeting transcripts.
//    Returns matching segments with meeting context.
//
//    /wp-json/cambridge-record/v1/meetings
//    Lightweight meeting index (no JSON blobs).
// ═══════════════════════════════════════════════════════

add_action( 'rest_api_init', 'cr_register_rest_routes' );

function cr_register_rest_routes() {

    // ── Transcript search ─────────────────────────────
    register_rest_route( 'cambridge-record/v1', '/search', [
        'methods'             => 'GET',
        'callback'            => 'cr_search_segments',
        'permission_callback' => '__return_true',
        'args' => [
            'q' => [
                'required'          => true,
                'type'              => 'string',
                'sanitize_callback' => 'sanitize_text_field',
                'description'       => 'Search query',
            ],
            'limit' => [
                'default'           => 20,
                'type'              => 'integer',
                'sanitize_callback' => 'absint',
            ],
        ],
    ] );

    // ── Meeting index (no blobs) ──────────────────────
    register_rest_route( 'cambridge-record/v1', '/meetings', [
        'methods'             => 'GET',
        'callback'            => 'cr_meeting_index',
        'permission_callback' => '__return_true',
    ] );
}


/**
 * Full-text search across all meeting transcript segments.
 *
 * Strategy: WordPress native search on post_content, which holds all
 * segment text concatenated. WordPress indexes post_content natively
 * so this is fast even as the archive grows. Once a matching meeting
 * is found, we filter its segments in PHP to return only the ones
 * containing the query term, with their deep-link URLs.
 *
 * Returns up to $limit matching segments, each with:
 *   - the matching segment object
 *   - meeting_id, meeting_date, meeting_body, embed_url
 *   - deep_link_url for jumping to the exact moment
 */
function cr_search_segments( WP_REST_Request $request ) {
    $query   = $request->get_param( 'q' );
    $limit   = min( $request->get_param( 'limit' ), 50 );
    $results = [];

    // Use WordPress native full-text search on post_content.
    // The pipeline stores all segment text in post_content for this purpose.
    $meetings = get_posts( [
        'post_type'      => 'cr_meeting',
        'post_status'    => 'publish',
        'posts_per_page' => -1,
        's'              => $query,
    ] );

    foreach ( $meetings as $meeting ) {
        $meta     = get_post_meta( $meeting->ID );
        $segments = json_decode( $meta['segments_json'][0] ?? '[]', true );

        if ( ! is_array( $segments ) ) continue;

        $query_lower = strtolower( $query );

        foreach ( $segments as $seg ) {
            if ( strpos( strtolower( $seg['text'] ?? '' ), $query_lower ) === false ) {
                continue;
            }

            $results[] = [
                'meeting_id'    => $meeting->ID,
                'meeting_date'  => $meta['meeting_date'][0]  ?? '',
                'meeting_body'  => $meta['meeting_body'][0]  ?? '',
                'meeting_title' => get_the_title( $meeting->ID ),
                'embed_url'     => $meta['cablecast_embed_url'][0] ?? '',
                'segment'       => $seg,
            ];

            if ( count( $results ) >= $limit ) break 2;
        }
    }

    return rest_ensure_response( [
        'query'   => $query,
        'count'   => count( $results ),
        'results' => $results,
    ] );
}


/**
 * Lightweight meeting index — returns all published meetings
 * with scalar meta only (no JSON blobs).
 * Used by the theme's meeting list page.
 */
function cr_meeting_index( WP_REST_Request $request ) {
    $meetings = get_posts( [
        'post_type'      => 'cr_meeting',
        'post_status'    => 'publish',
        'posts_per_page' => 100,
        'orderby'        => 'meta_value',
        'meta_key'       => 'meeting_date',
        'order'          => 'DESC',
    ] );

    $index = array_map( function( $m ) {
        $meta = get_post_meta( $m->ID );
        return [
            'id'             => $m->ID,
            'title'          => get_the_title( $m->ID ),
            'slug'           => $m->post_name,
            'meeting_date'   => $meta['meeting_date'][0]   ?? '',
            'meeting_body'   => $meta['meeting_body'][0]   ?? '',
            'embed_url'      => $meta['cablecast_embed_url'][0] ?? '',
            'agenda_url'     => $meta['agenda_url'][0]     ?? '',
            'segment_count'  => (int)( $meta['segment_count'][0]  ?? 0 ),
            'vote_count'     => (int)( $meta['vote_count'][0]     ?? 0 ),
            'summary'        => $meta['summary'][0]        ?? '',
            'summary_origin' => $meta['summary_origin'][0] ?? '',
            'languages'      => $meta['languages_available'][0] ?? '',
            'permalink'      => get_permalink( $m->ID ),
        ];
    }, $meetings );

    return rest_ensure_response( [ 'meetings' => $index ] );
}


// ═══════════════════════════════════════════════════════
// 4. INCREASE REST API PAGE SIZE FOR MEETINGS
//    The pipeline may need to fetch all meetings at once.
// ═══════════════════════════════════════════════════════

add_filter( 'rest_cr_meeting_query', function( $args, $request ) {
    $per_page = (int) $request->get_param( 'per_page' );
    if ( $per_page > 100 ) {
        $args['posts_per_page'] = min( $per_page, 200 );
    }
    return $args;
}, 10, 2 );


// ═══════════════════════════════════════════════════════
// 5. ADMIN COLUMNS
//    Makes the Meetings list in WP admin more useful
//    by showing date, publish status, pipeline status,
//    and segment count.
// ═══════════════════════════════════════════════════════

add_filter( 'manage_cr_meeting_posts_columns', function( $cols ) {
    return [
        'cb'            => $cols['cb'],
        'title'         => 'Meeting',
        'meeting_date'  => 'Date',
        'segment_count' => 'Segments',
        'vote_count'    => 'Votes',
        'publish_state' => 'Published',
        'cr_status'     => 'Pipeline',
    ];
} );

add_action( 'manage_cr_meeting_posts_custom_column', function( $col, $post_id ) {
    switch ( $col ) {
        case 'meeting_date':
            echo esc_html( get_post_meta( $post_id, 'meeting_date', true ) );
            break;
        case 'segment_count':
            echo (int) get_post_meta( $post_id, 'segment_count', true );
            break;
        case 'vote_count':
            echo (int) get_post_meta( $post_id, 'vote_count', true );
            break;
        case 'publish_state':
            // WordPress's own status — whether residents can see the meeting.
            $post_status = get_post_status( $post_id );
            $color = match( $post_status ) {
                'publish' => '#2ecc71',
                'future'  => '#3498db',
                'pending' => '#e67e22',
                default   => '#999',
            };
            $label = $post_status === 'publish'
                ? 'Published'
                : ( get_post_status_object( $post_status )->label ?? $post_status );
            printf(
                '<span style="color:%s;font-weight:600;">%s</span>',
                esc_attr( $color ),
                esc_html( $label )
            );
            break;
        case 'cr_status':
            // Pipeline progress, written by ingest_cablecast.py.
            $status = get_post_meta( $post_id, 'cr_status', true );
            $color  = match( $status ) {
                'published'  => '#2ecc71',
                'ready'      => '#3498db',
                'processing' => '#e67e22',
                default      => '#999',
            };
            printf(
                '<span style="color:%s;font-weight:600;">%s</span>',
                esc_attr( $color ),
                esc_html( $status ?: 'unknown' )
            );
            break;
    }
}, 10, 2 );

add_filter( 'manage_edit-cr_meeting_sortable_columns', function( $cols ) {
    $cols['meeting_date'] = 'meeting_date';
    return $cols;
} );


// ═══════════════════════════════════════════════════════
// 6. ACTIVATION / DEACTIVATION
// ═══════════════════════════════════════════════════════

register_activation_hook( __FILE__, function () {
    cr_register_post_types();
    flush_rewrite_rules();
} );

register_deactivation_hook( __FILE__, function () {
    flush_rewrite_rules();
} );
