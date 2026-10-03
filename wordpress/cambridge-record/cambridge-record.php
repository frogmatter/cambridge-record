<?php
/**
 * Plugin Name: Cambridge Record
 * Description: Civic meeting archive for Cambridge Public Schools.
 *              Single post per meeting — segments, agenda items, and votes
 *              stored as JSON in post meta. Designed for shared hosting.
 *              No plugin dependencies. REST API ready for the local pipeline.
 * Version:     0.5.1
 * Author:      Matt / Cambridge Public Schools
 * License:     CC BY-SA 4.0
 * Site:        mediatechaction.com
 */

defined( 'ABSPATH' ) || exit;

define( 'CR_PLUGIN_VERSION', '0.5.1' );

require_once __DIR__ . '/includes/review.php';


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
        'has_archive'        => 'officials',
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
        'cr_status'              => 'string',   // ingest progress: 'processing' | 'ready' (not visibility — that's post_status)
        'caption_corrections'    => 'integer',  // fixes applied from cambridge_terms.txt (originals kept per segment)
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

        // People's decisions from Meetings → Review times, keyed by item key:
        // {votes: {key: {status, start_seconds, by, at}}, agenda: {…}}.
        // enrich_meetings.py re-applies these after every run.
        'review_json'        => 'string',
    ];
    cr_register_meta_group( 'cr_meeting', $meeting_json );

    // ── cr_official ───────────────────────────────────
    $official_fields = [
        'full_name'          => 'string',
        'official_title'     => 'string',   // 'Chair' | 'Vice Chair' | 'Mayor' | 'Member' | 'Student Member'
        'term_start'         => 'string',   // YYYY-MM-DD
        'term_end'           => 'string',   // YYYY-MM-DD or empty if current
        'is_voting_member'   => 'boolean',
        'minutes_name'       => 'string',   // surname as the minutes write it: 'Weinstein', 'de Paula Santos'
        'subcommittees_json' => 'string',   // [{name, role}] — role 'Chair' | 'Co-Chair' | 'Member'
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
//
//    /wp-json/cambridge-record/v1/officials[/{id}]
//    /wp-json/cambridge-record/v1/officials/{name}/votes
//    Officials and voting records, from the vote index (3c).
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
            'per_meeting' => [
                'default'           => 5,
                'type'              => 'integer',
                'sanitize_callback' => 'absint',
                'description'       => 'Transcript moments returned per meeting (all are counted)',
            ],
        ],
    ] );

    // ── Meeting index (no blobs) ──────────────────────
    register_rest_route( 'cambridge-record/v1', '/meetings', [
        'methods'             => 'GET',
        'callback'            => 'cr_meeting_index',
        'permission_callback' => '__return_true',
        'args' => [
            'page' => [
                'default'           => 1,
                'type'              => 'integer',
                'sanitize_callback' => 'absint',
            ],
            'per_page' => [
                'default'           => 20,
                'type'              => 'integer',
                'sanitize_callback' => 'absint',
                'description'       => 'Meetings per page (max 200)',
            ],
        ],
    ] );

    // ── Officials + voting records ────────────────────
    register_rest_route( 'cambridge-record/v1', '/officials', [
        'methods'             => 'GET',
        'callback'            => 'cr_officials_index',
        'permission_callback' => '__return_true',
    ] );
    register_rest_route( 'cambridge-record/v1', '/officials/(?P<id>\d+)', [
        'methods'             => 'GET',
        'callback'            => 'cr_official_record',
        'permission_callback' => '__return_true',
        'args'                => [ 'id' => [ 'sanitize_callback' => 'absint' ] ],
    ] );
    register_rest_route( 'cambridge-record/v1', '/officials/(?P<name>[^/]+)/votes', [
        'methods'             => 'GET',
        'callback'            => 'cr_official_votes_by_name',
        'permission_callback' => '__return_true',
    ] );
}


/**
 * Search across all published meetings: transcript moments and agenda items.
 *
 * Candidate meetings come from WordPress native search on post_content
 * (the pipeline stores all transcript text there), run for both straight
 * and curly apostrophes. Each candidate's segments are then matched in PHP
 * at the start of a word ("transport" finds "transportation", "art"
 * doesn't find "start"). Agenda titles are matched in every meeting, since
 * they aren't part of post_content.
 *
 * Response:
 *   meetings: [{meeting_id, meeting_title, meeting_date, permalink,
 *               match_count, hits: [segment…] (first per_meeting),
 *               agenda_hits: [{docket, title, start_seconds, vote}]}]
 *             newest meeting first
 *   count / meeting_count: totals
 *   results: flat list of the first `limit` hits (the 0.2 response shape)
 */
function cr_search_segments( WP_REST_Request $request ) {
    $query       = trim( (string) $request->get_param( 'q' ) );
    $limit       = min( max( (int) $request->get_param( 'limit' ), 1 ), 200 );
    $per_meeting = min( max( (int) ( $request->get_param( 'per_meeting' ) ?: 5 ), 1 ), 50 );
    $needle      = cr_search_normalize( $query );

    $empty = [ 'query' => $query, 'count' => 0, 'meeting_count' => 0, 'meetings' => [], 'results' => [] ];
    if ( mb_strlen( $needle ) < 2 ) {
        return rest_ensure_response( $empty );
    }
    $pattern = '/(?<![\p{L}\p{N}])' . preg_quote( $needle, '/' ) . '/iu';

    $published = get_posts( [
        'post_type'      => 'cr_meeting',
        'post_status'    => 'publish',
        'posts_per_page' => -1,
        'fields'         => 'ids',
    ] );

    $transcript_ids = [];
    foreach ( array_unique( [ $query, str_replace( "'", '’', $query ), str_replace( '’', "'", $query ) ] ) as $variant ) {
        $transcript_ids = array_merge( $transcript_ids, get_posts( [
            'post_type'      => 'cr_meeting',
            'post_status'    => 'publish',
            'posts_per_page' => -1,
            'fields'         => 'ids',
            's'              => $variant,
        ] ) );
    }
    $transcript_ids = array_flip( $transcript_ids );

    $groups = [];
    foreach ( $published as $id ) {
        $hits = [];
        $match_count = 0;
        if ( isset( $transcript_ids[ $id ] ) ) {
            $segments = json_decode( get_post_meta( $id, 'segments_json', true ) ?: '[]', true );
            foreach ( is_array( $segments ) ? $segments : [] as $seg ) {
                if ( preg_match( $pattern, cr_search_normalize( $seg['text'] ?? '' ) ) ) {
                    $match_count++;
                    if ( count( $hits ) < $per_meeting ) {
                        $hits[] = $seg;
                    }
                }
            }
        }

        $agenda_hits = [];
        $agenda = json_decode( get_post_meta( $id, 'agenda_json', true ) ?: '[]', true );
        $votes  = json_decode( get_post_meta( $id, 'votes_json', true ) ?: '[]', true );
        $votes_by_index = [];
        foreach ( is_array( $votes ) ? $votes : [] as $v ) {
            $votes_by_index[ $v['index'] ?? -1 ] = $v;
        }
        foreach ( is_array( $agenda ) ? $agenda : [] as $item ) {
            if ( ( $item['item_type'] ?? '' ) === 'section' ) {
                continue;
            }
            $haystack = cr_search_normalize( ( $item['docket'] ?? '' ) . ' ' . ( $item['title'] ?? '' ) );
            if ( ! preg_match( $pattern, $haystack ) ) {
                continue;
            }
            $vote = null;
            foreach ( array_reverse( $item['vote_indexes'] ?? [] ) as $vi ) {
                if ( isset( $votes_by_index[ $vi ] ) ) {
                    $v = $votes_by_index[ $vi ];
                    $vote = [ 'result' => $v['result'] ?? '', 'passed' => $v['passed'] ?? null,
                              'vote_for' => $v['vote_for'] ?? null, 'vote_against' => $v['vote_against'] ?? null ];
                    break;
                }
            }
            $agenda_hits[] = [
                'docket'        => $item['docket'] ?? null,
                'title'         => $item['title'] ?? '',
                'item_type'     => $item['item_type'] ?? '',
                'start_seconds' => $item['start_seconds'] ?? null,
                'vote'          => $vote,
            ];
        }

        if ( ! $match_count && ! $agenda_hits ) {
            continue;
        }
        $groups[] = [
            'meeting_id'    => $id,
            'meeting_title' => get_the_title( $id ),
            'meeting_date'  => get_post_meta( $id, 'meeting_date', true ),
            'meeting_body'  => get_post_meta( $id, 'meeting_body', true ),
            'embed_url'     => get_post_meta( $id, 'cablecast_embed_url', true ),
            'permalink'     => get_permalink( $id ),
            'match_count'   => $match_count,
            'hits'          => $hits,
            'agenda_hits'   => $agenda_hits,
        ];
    }

    usort( $groups, fn( $a, $b ) => strcmp( $b['meeting_date'], $a['meeting_date'] ) );

    // Flat list in the 0.2 shape, for older themes
    $results = [];
    foreach ( $groups as $g ) {
        foreach ( $g['hits'] as $seg ) {
            if ( count( $results ) >= $limit ) {
                break 2;
            }
            $results[] = [
                'meeting_id'    => $g['meeting_id'],
                'meeting_date'  => $g['meeting_date'],
                'meeting_body'  => $g['meeting_body'],
                'meeting_title' => $g['meeting_title'],
                'embed_url'     => $g['embed_url'],
                'segment'       => $seg,
            ];
        }
    }

    return rest_ensure_response( [
        'query'         => $query,
        'count'         => array_sum( array_column( $groups, 'match_count' ) ),
        'meeting_count' => count( $groups ),
        'meetings'      => $groups,
        'results'       => $results,
    ] );
}

/** Lowercase, curly apostrophes → straight, so "don't" finds "don’t". */
function cr_search_normalize( $text ) {
    return mb_strtolower( str_replace( [ '’', '‘' ], "'", (string) $text ) );
}


/**
 * Lightweight meeting index — published meetings, newest first,
 * with scalar meta only (no JSON blobs). Paged with ?page and
 * ?per_page (default 20, max 200); callers that need every meeting
 * (the theme's meeting list and search) follow total_pages.
 */
function cr_meeting_index( WP_REST_Request $request ) {
    $page     = max( (int) $request->get_param( 'page' ), 1 );
    $per_page = min( max( (int) $request->get_param( 'per_page' ), 1 ), 200 );

    $query = new WP_Query( [
        'post_type'      => 'cr_meeting',
        'post_status'    => 'publish',
        'posts_per_page' => $per_page,
        'paged'          => $page,
        'orderby'        => 'meta_value',
        'meta_key'       => 'meeting_date',
        'order'          => 'DESC',
    ] );
    $meetings = $query->posts;

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

    return rest_ensure_response( [
        'meetings'    => $index,
        'page'        => $page,
        'per_page'    => $per_page,
        'total_count' => (int) $query->found_posts,
        'total_pages' => (int) $query->max_num_pages,
    ] );
}


// ═══════════════════════════════════════════════════════
// 3b. OFFICIALS & VOTING RECORDS
//     Votes live in each meeting's votes_json (parsed from
//     the official minutes by the pipeline). Each roll-call
//     entry names a member as the minutes do — "Member de
//     Paula Santos", "Vice Chair Dube" — so an official is
//     matched on their minutes_name (surname), ignoring the
//     title, case and spacing. Titles change; surnames don't.
// ═══════════════════════════════════════════════════════

/** 'Vice Chair de Paula Santos' / 'DePaula Santos' → 'depaulasantos' */
function cr_name_key( $name ) {
    $name = preg_replace( '/^(Vice Chair|Chair|Mayor|Member|Memer)\s+/i', '', trim( (string) $name ) );
    return strtolower( preg_replace( '/[^a-z]/i', '', $name ) );
}

/** Results that don't decide an agenda item (closing public comment, adjourning…). */
function cr_is_procedural_vote( array $vote ) {
    if ( ! empty( $vote['dockets'] ) || ! empty( $vote['items'] ) ) {
        return false;
    }
    return in_array( $vote['result'] ?? '', [
        'closed', 'reopened', 'adjourned', 'extended', 'rules suspended',
        'brought forward', 'executive session', 'approved', 'accepted',
    ], true );
}

/** Published officials, ordered Chair, Vice Chair, Mayor, members A–Z, then non-voting. */
function cr_get_officials() {
    $posts = get_posts( [
        'post_type'      => 'cr_official',
        'post_status'    => 'publish',
        'posts_per_page' => -1,
    ] );
    $rank = [ 'Chair' => 0, 'Vice Chair' => 1, 'Mayor' => 2, 'Member' => 3 ];

    $officials = array_map( function ( $p ) use ( $rank ) {
        $meta = get_post_meta( $p->ID );
        $title = $meta['official_title'][0] ?? 'Member';
        return [
            'id'            => $p->ID,
            'name'          => get_the_title( $p->ID ),
            'full_name'     => $meta['full_name'][0] ?? get_the_title( $p->ID ),
            'title'         => $title,
            'minutes_name'  => $meta['minutes_name'][0] ?? '',
            'is_voting'     => ! empty( $meta['is_voting_member'][0] ),
            'term_start'    => $meta['term_start'][0] ?? '',
            'term_end'      => $meta['term_end'][0] ?? '',
            'subcommittees' => json_decode( $meta['subcommittees_json'][0] ?? '[]', true ) ?: [],
            'permalink'     => get_permalink( $p->ID ),
            '_rank'         => ( empty( $meta['is_voting_member'][0] ) ? 10 : 0 ) + ( $rank[ $title ] ?? 5 ),
            '_sort'         => strtolower( $meta['minutes_name'][0] ?? get_the_title( $p->ID ) ),
        ];
    }, $posts );

    usort( $officials, fn( $a, $b ) => [ $a['_rank'], $a['_sort'] ] <=> [ $b['_rank'], $b['_sort'] ] );
    return array_map( function ( $o ) { unset( $o['_rank'], $o['_sort'] ); return $o; }, $officials );
}

/** Summary counts for a member with no votes yet. */
function cr_empty_vote_summary() {
    return [ 'votes' => 0, 'yea' => 0, 'nay' => 0, 'absent' => 0, 'present' => 0, 'abstain' => 0, 'dissents' => 0, 'meetings' => 0 ];
}

/**
 * Every roll-call vote cast by the member with this minutes_name, across
 * published meetings (newest first), plus summary counts — from the vote index.
 */
function cr_voting_record( $minutes_name ) {
    $index = cr_get_vote_index();
    $entry = $index['members'][ cr_name_key( $minutes_name ) ] ?? null;
    return $entry ? [ $entry['votes'], $entry['summary'] ] : [ [], cr_empty_vote_summary() ];
}


// ═══════════════════════════════════════════════════════
// 3c. VOTE INDEX
//     Every member's voting record, built once from all
//     published meetings' votes_json and kept in the
//     cr_vote_index option (not autoloaded), keyed by
//     cr_name_key(). Any change that could alter a record
//     — votes or date written (REST or Review times), a
//     meeting saved, published, unpublished or deleted —
//     drops the index; the next request rebuilds it.
//
//     Dropping rather than rebuilding on save matters: a
//     REST update fires save_post *before* it writes meta,
//     so a rebuild there would read the old votes_json.
// ═══════════════════════════════════════════════════════

/** The index, decoded once per request; pass $drop to forget it. */
function cr_get_vote_index( $drop = false ) {
    static $index = null;
    if ( $drop ) {
        $index = null;
        return null;
    }
    if ( $index === null ) {
        $stored = get_option( 'cr_vote_index' );
        $index  = $stored ? json_decode( $stored, true ) : null;
        if ( ! is_array( $index ) ) {
            $index = cr_build_vote_index();
            update_option( 'cr_vote_index', wp_json_encode( $index ), false );
        }
    }
    return $index;
}

/** Records for every member named in a published meeting's roll calls. */
function cr_build_vote_index() {
    global $wpdb;

    // Read the two meta fields directly: get_post_meta() would also load
    // each meeting's ~1 MB segments_json into memory.
    $rows = $wpdb->get_results(
        "SELECT p.ID, d.meta_value AS meeting_date, v.meta_value AS votes_json
           FROM {$wpdb->posts} p
           JOIN {$wpdb->postmeta} d ON d.post_id = p.ID AND d.meta_key = 'meeting_date'
           LEFT JOIN {$wpdb->postmeta} v ON v.post_id = p.ID AND v.meta_key = 'votes_json'
          WHERE p.post_type = 'cr_meeting' AND p.post_status = 'publish'
          ORDER BY d.meta_value DESC, p.ID DESC"
    );

    $members = [];
    foreach ( $rows as $row ) {
        $votes = json_decode( maybe_unserialize( $row->votes_json ) ?: '[]', true );
        if ( ! is_array( $votes ) ) {
            continue;
        }
        $permalink = get_permalink( $row->ID );
        $title     = get_the_title( $row->ID );
        $in_meeting = [];

        foreach ( $votes as $v ) {
            if ( ( $v['source'] ?? '' ) !== 'minutes' ) {
                continue;   // caption-flagged guesses have no per-member votes
            }
            $passed     = $v['passed'] ?? true;
            $procedural = cr_is_procedural_vote( $v );
            $seen       = [];

            foreach ( $v['roll_call'] ?? [] as $entry ) {
                $key  = cr_name_key( $entry['member'] ?? '' );
                $cast = $entry['vote'] ?? null;
                if ( ! $key || $cast === null || isset( $seen[ $key ] ) ) {
                    continue;
                }
                $seen[ $key ] = true;
                $members[ $key ] ??= [ 'summary' => cr_empty_vote_summary(), 'votes' => [] ];
                $m = &$members[ $key ];

                // Dissent: voted against the outcome (nay on a passed motion, yea on a failed one)
                $dissent = ( $cast === 'NAY' && $passed ) || ( $cast === 'YEA' && ! $passed );

                $m['summary']['votes']++;
                $bucket = strtolower( $cast === 'RECUSED' ? 'abstain' : $cast );
                if ( isset( $m['summary'][ $bucket ] ) ) {
                    $m['summary'][ $bucket ]++;
                }
                if ( $dissent ) {
                    $m['summary']['dissents']++;
                }
                if ( ! isset( $in_meeting[ $key ] ) ) {
                    $in_meeting[ $key ] = true;
                    $m['summary']['meetings']++;
                }

                $m['votes'][] = [
                    'meeting_id'    => (int) $row->ID,
                    'meeting_title' => $title,
                    'meeting_date'  => $row->meeting_date,
                    'meeting_url'   => $permalink,
                    'vote_index'    => $v['index'] ?? null,
                    'motion_text'   => $v['motion_text'] ?? '',
                    'items'         => $v['items'] ?? [],
                    'section_title' => $v['section_title'] ?? null,
                    'result'        => $v['result'] ?? '',
                    'passed'        => $passed,
                    'vote_for'      => $v['vote_for'] ?? null,
                    'vote_against'  => $v['vote_against'] ?? null,
                    'member_vote'   => $cast,
                    'member_candidate' => $cast === 'CANDIDATE' ? ( $entry['candidate'] ?? null ) : null,
                    'dissent'       => $dissent,
                    'procedural'    => $procedural,
                    'start_seconds' => $v['start_seconds'] ?? null,
                    'moment_url'    => isset( $v['start_seconds'] )
                        ? $permalink . '#t=' . (int) $v['start_seconds']
                        : $permalink,
                ];
                unset( $m );
            }
        }
    }

    return [ 'built_at' => gmdate( 'c' ), 'meeting_count' => count( $rows ), 'members' => $members ];
}

function cr_drop_vote_index() {
    delete_option( 'cr_vote_index' );
    cr_get_vote_index( true );
}

add_action( 'save_post_cr_meeting', 'cr_drop_vote_index' );

add_action( 'transition_post_status', function ( $new, $old, $post ) {
    if ( $post->post_type === 'cr_meeting' && $new !== $old ) {
        cr_drop_vote_index();
    }
}, 10, 3 );

add_action( 'deleted_post', function ( $post_id, $post = null ) {
    if ( ( $post->post_type ?? get_post_type( $post_id ) ) === 'cr_meeting' ) {
        cr_drop_vote_index();
    }
}, 10, 2 );

// Meta writes: REST updates write meta after save_post; Review times writes it directly.
foreach ( [ 'added_post_meta', 'updated_post_meta', 'deleted_post_meta' ] as $cr_meta_hook ) {
    add_action( $cr_meta_hook, function ( $meta_id, $post_id, $meta_key ) {
        if ( in_array( $meta_key, [ 'votes_json', 'meeting_date' ], true )
            && get_post_type( $post_id ) === 'cr_meeting' ) {
            cr_drop_vote_index();
        }
    }, 10, 3 );
}
unset( $cr_meta_hook );

function cr_officials_index( WP_REST_Request $request ) {
    $officials = array_map( function ( $o ) {
        [ , $summary ] = cr_voting_record( $o['minutes_name'] );
        return $o + [ 'summary' => $summary ];
    }, cr_get_officials() );
    return rest_ensure_response( [ 'officials' => $officials ] );
}

function cr_official_record( WP_REST_Request $request ) {
    $id = (int) $request['id'];
    $official = null;
    foreach ( cr_get_officials() as $o ) {
        if ( $o['id'] === $id ) {
            $official = $o;
        }
    }
    if ( ! $official ) {
        return new WP_Error( 'cr_not_found', 'Official not found', [ 'status' => 404 ] );
    }
    [ $record, $summary ] = cr_voting_record( $official['minutes_name'] );
    return rest_ensure_response( $official + [ 'summary' => $summary, 'votes' => $record ] );
}

/**
 * One member's record by name, e.g. /officials/dube/votes or
 * /officials/de-paula-santos/votes — matched like the minutes are
 * (cr_name_key: title, case, spaces and punctuation ignored).
 */
function cr_official_votes_by_name( WP_REST_Request $request ) {
    $key = cr_name_key( urldecode( (string) $request['name'] ) );
    $official = null;
    foreach ( cr_get_officials() as $o ) {
        if ( $key && cr_name_key( $o['minutes_name'] ) === $key ) {
            $official = $o;
        }
    }
    $entry = cr_get_vote_index()['members'][ $key ] ?? null;
    if ( ! $official && ! $entry ) {
        return new WP_Error( 'cr_not_found', 'No official or votes for that name', [ 'status' => 404 ] );
    }
    return rest_ensure_response( [
        'name_key' => $key,
        'official' => $official,
        'summary'  => $entry['summary'] ?? cr_empty_vote_summary(),
        'votes'    => $entry['votes'] ?? [],
    ] );
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
//    by showing date, publish status, ingest progress,
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
        'cr_status'     => 'Ingest',
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
            // Ingest progress, written by ingest_cablecast.py. Says nothing
            // about visibility — that's the Published column.
            $status = get_post_meta( $post_id, 'cr_status', true );
            [ $label, $color ] = match( $status ) {
                'ready'      => [ 'Transcript in', '#3498db' ],
                'processing' => [ 'Ingesting…', '#e67e22' ],
                default      => [ $status ?: 'unknown', '#999' ],
            };
            printf(
                '<span style="color:%s;font-weight:600;" title="%s">%s</span>',
                esc_attr( $color ),
                esc_attr( 'Pipeline progress only — whether residents can see this meeting is in the Published column.' ),
                esc_html( $label )
            );
            break;
    }
}, 10, 2 );

add_filter( 'manage_edit-cr_meeting_sortable_columns', function( $cols ) {
    $cols['meeting_date'] = 'meeting_date';
    return $cols;
} );


// ═══════════════════════════════════════════════════════
// 5b. OFFICIALS ADMIN COLUMNS
// ═══════════════════════════════════════════════════════

add_filter( 'manage_cr_official_posts_columns', function( $cols ) {
    return [
        'cb'             => $cols['cb'],
        'title'          => 'Official',
        'official_title' => 'Title',
        'minutes_name'   => 'Name in minutes',
        'voting'         => 'Voting',
        'term'           => 'Term',
    ];
} );

add_action( 'manage_cr_official_posts_custom_column', function( $col, $post_id ) {
    switch ( $col ) {
        case 'official_title':
        case 'minutes_name':
            echo esc_html( get_post_meta( $post_id, $col, true ) );
            break;
        case 'voting':
            echo get_post_meta( $post_id, 'is_voting_member', true ) ? 'Yes' : 'No';
            break;
        case 'term':
            echo esc_html( trim( get_post_meta( $post_id, 'term_start', true ) . ' – ' . get_post_meta( $post_id, 'term_end', true ), ' –' ) );
            break;
    }
}, 10, 2 );


// ═══════════════════════════════════════════════════════
// 6. ACTIVATION / DEACTIVATION / UPDATE
//    Uploading a new plugin version doesn't re-run the
//    activation hook, so flush rewrite rules once when the
//    version changes (new URLs like /officials/).
// ═══════════════════════════════════════════════════════

add_action( 'init', function () {
    if ( get_option( 'cr_plugin_version' ) !== CR_PLUGIN_VERSION ) {
        flush_rewrite_rules();
        cr_drop_vote_index();   // the index format may have changed
        update_option( 'cr_plugin_version', CR_PLUGIN_VERSION );
    }
}, 20 );

register_activation_hook( __FILE__, function () {
    cr_register_post_types();
    flush_rewrite_rules();
} );

register_deactivation_hook( __FILE__, function () {
    flush_rewrite_rules();
} );
