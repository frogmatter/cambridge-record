/**
 * Transcript search — /?s=term
 * Source: GET /wp-json/cambridge-record/v1/search?q=&limit=
 *         GET /wp-json/cambridge-record/v1/meetings (for permalinks)
 */
( function () {
    'use strict';

    const { api, allMeetings, el, fmtDate, fmtTime, highlight, momentUrl, status, config } = window.CR;

    const LIMIT = 50; // the endpoint caps results at 50

    const resultsEl = document.getElementById( 'search-results' );
    const summaryEl = document.getElementById( 'search-summary' );
    const form      = document.querySelector( '.search-head .cr-search-form' );
    const input     = form && form.querySelector( 'input[name="s"]' );
    if ( ! resultsEl || ! input ) return;

    // The search endpoint returns meeting IDs but not permalinks, so we
    // look them up from the meeting index (fetched once, lazily).
    let permalinksPromise = null;
    function permalinks() {
        if ( ! permalinksPromise ) {
            permalinksPromise = allMeetings()
                .then( ( meetings ) => new Map( meetings.map( ( m ) => [ m.id, m.permalink ] ) ) )
                .catch( () => new Map() );
        }
        return permalinksPromise;
    }

    function meetingUrl( links, id, permalink ) {
        return permalink || links.get( id ) || `${ config.homeUrl }?post_type=cr_meeting&p=${ id }`;
    }

    /** Plugin 0.2 returned a flat list of hits; group it the way 0.3.1+ does. */
    function group( results ) {
        const byMeeting = new Map();
        results.forEach( ( r ) => {
            if ( ! byMeeting.has( r.meeting_id ) ) {
                byMeeting.set( r.meeting_id, { ...r, hits: [] } );
            }
            byMeeting.get( r.meeting_id ).hits.push( r.segment );
        } );
        return [ ...byMeeting.values() ]
            .sort( ( a, b ) => ( b.meeting_date || '' ).localeCompare( a.meeting_date || '' ) )
            .map( ( g ) => ( { ...g, match_count: g.hits.length, hits: g.hits.sort( ( a, b ) => a.start_seconds - b.start_seconds ) } ) );
    }

    const PER_MEETING = 5;

    function agendaHit( a, url, q ) {
        const vote = a.vote;
        return el( 'li', { class: 'hit hit--agenda' },
            el( 'a', { href: momentUrl( url, a.start_seconds, null ) },
                el( 'span', { class: 'hit__time' }, a.start_seconds !== null && a.start_seconds !== undefined ? fmtTime( a.start_seconds ) : 'Agenda' ),
                el( 'span', { class: 'hit__text' },
                    el( 'span', { class: 'tag' }, 'Agenda' ), ' ',
                    a.docket ? `#${ a.docket } ` : '', highlight( a.title, q ),
                    vote ? [ ' ', el( 'span', { class: vote.passed === false ? 'tag tag--failed' : 'tag tag--vote' }, vote.result ),
                             vote.vote_for !== null && vote.vote_for !== undefined ? ` ${ vote.vote_for }–${ vote.vote_against }` : '' ] : null
                )
            )
        );
    }

    function renderGroup( g, links, q ) {
        const url = meetingUrl( links, g.meeting_id, g.permalink );
        const more = g.match_count - g.hits.length;
        return el( 'section', { class: 'result-group' },
            el( 'div', { class: 'result-group__head' },
                el( 'h2', {}, el( 'a', { href: momentUrl( url, null, q ) }, g.meeting_title || 'Untitled meeting' ) ),
                el( 'span', { class: 'muted' },
                    [ fmtDate( g.meeting_date, { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' } ),
                      g.match_count ? `${ g.match_count } moment${ g.match_count === 1 ? '' : 's' }` : null ].filter( Boolean ).join( ' · ' ) )
            ),
            el( 'ol', { class: 'hits' },
                ( g.agenda_hits || [] ).map( ( a ) => agendaHit( a, url, q ) ),
                g.hits.map( ( seg ) =>
                    el( 'li', { class: 'hit' },
                        el( 'a', { href: momentUrl( url, seg.start_seconds, q ) },
                            el( 'span', { class: 'hit__time' }, fmtTime( seg.start_seconds ) ),
                            el( 'span', { class: 'hit__text' },
                                highlight( String( seg.text || '' ).replace( />>+/g, '' ).trim(), q ),
                                seg.is_vote ? [ ' ', el( 'span', { class: 'tag tag--vote' }, 'vote' ) ] : null )
                        )
                    )
                )
            ),
            more > 0
                ? el( 'p', { class: 'more-hits' }, el( 'a', { href: momentUrl( url, null, q ) }, `See all ${ g.match_count } moments in this meeting →` ) )
                : null
        );
    }

    let requestId = 0;

    async function run( q ) {
        const id = ++requestId;
        q = q.trim();
        document.title = [ q ? `“${ q }”` : 'Search', config.siteName ].filter( Boolean ).join( ' – ' );

        if ( q.length < 2 ) {
            summaryEl.textContent = '';
            resultsEl.replaceChildren(
                el( 'p', { class: 'status' }, 'Search for any word or phrase said in a meeting. Each result links to that moment in the video.' )
            );
            return;
        }

        summaryEl.textContent = '';
        resultsEl.replaceChildren( el( 'p', { class: 'status loading' }, `Searching for “${ q }”` ) );

        try {
            const data = await api( 'cambridge-record/v1/search', { q, limit: LIMIT, per_meeting: PER_MEETING } );
            // Plugin 0.3.1+ groups by meeting; older plugins return a flat list
            const links = data.meetings ? new Map() : await permalinks();
            if ( id !== requestId ) return; // a newer search started

            const groups = data.meetings || group( data.results || [] );
            if ( ! groups.length ) {
                summaryEl.textContent = `No moments found for “${ q }”.`;
                status( resultsEl, 'Try a shorter phrase, a different spelling, or a single keyword. Captions are machine-generated, so names are sometimes misspelled.' );
                return;
            }

            const n = data.count;
            const capped = ! data.meetings && n >= LIMIT;
            const items = groups.reduce( ( sum, g ) => sum + ( g.agenda_hits || [] ).length, 0 );
            summaryEl.textContent = [
                n ? `${ n }${ capped ? '+' : '' } moment${ n === 1 ? '' : 's' }` : null,
                items ? `${ items } agenda item${ items === 1 ? '' : 's' }` : null,
            ].filter( Boolean ).join( ' and ' ) + ` in ${ groups.length } meeting${ groups.length === 1 ? '' : 's' }`;

            resultsEl.replaceChildren(
                ...groups.map( ( g ) => renderGroup( g, links, q ) ),
                capped
                    ? el( 'p', { class: 'search-note' }, `Showing the first ${ LIMIT } moments. Try a more specific phrase to narrow results.` )
                    : null
            );
        } catch ( e ) {
            if ( id !== requestId ) return;
            status( resultsEl, 'Search failed. Please try again.', true );
        }
    }

    form.addEventListener( 'submit', ( e ) => {
        e.preventDefault();
        const q = input.value.trim();
        const url = new URL( window.location.href );
        url.searchParams.set( 's', q );
        history.pushState( { q }, '', url );
        run( q );
    } );

    window.addEventListener( 'popstate', () => {
        const q = new URLSearchParams( window.location.search ).get( 's' ) || '';
        input.value = q;
        run( q );
    } );

    run( input.value );
    if ( ! input.value ) input.focus();
} )();
