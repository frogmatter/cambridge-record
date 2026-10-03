/**
 * Cambridge Record — shared helpers.
 * Exposes window.CR. Page scripts (meetings.js, search.js, meeting.js) use it.
 */
( function () {
    'use strict';

    const config = window.CR_CONFIG || { restRoot: '/wp-json/', nonce: '', homeUrl: '/' };

    /** GET a REST route, e.g. api('cambridge-record/v1/search', { q: 'budget' }). */
    async function api( route, params = {} ) {
        const url = new URL( config.restRoot, window.location.href );
        route = route.replace( /^\//, '' );
        if ( url.searchParams.has( 'rest_route' ) ) {
            // Plain permalinks: rest_url() is "/?rest_route=/"
            url.searchParams.set( 'rest_route', url.searchParams.get( 'rest_route' ).replace( /\/?$/, '/' ) + route );
        } else {
            url.pathname = url.pathname.replace( /\/?$/, '/' ) + route;
        }
        Object.entries( params ).forEach( ( [ k, v ] ) => {
            if ( v !== undefined && v !== null && v !== '' ) url.searchParams.set( k, v );
        } );
        const headers = { Accept: 'application/json' };
        if ( config.nonce ) headers[ 'X-WP-Nonce' ] = config.nonce;

        const res = await fetch( url, { headers, credentials: 'same-origin' } );
        if ( ! res.ok ) {
            throw new Error( `Request failed (${ res.status })` );
        }
        return res.json();
    }

    /** Every published meeting, following the index's pages. */
    async function allMeetings() {
        const meetings = [];
        for ( let page = 1, pages = 1; page <= pages; page++ ) {
            const data = await api( 'cambridge-record/v1/meetings', { page, per_page: 200 } );
            meetings.push( ...( data.meetings || [] ) );
            pages = data.total_pages || 1;   // plugin < 0.4.2 isn't paged
        }
        return meetings;
    }

    /** Parse a JSON meta string; returns fallback on empty or invalid input. */
    function parseJson( value, fallback = [] ) {
        if ( Array.isArray( value ) ) return value;
        if ( ! value ) return fallback;
        try {
            const parsed = JSON.parse( value );
            return Array.isArray( parsed ) ? parsed : fallback;
        } catch ( e ) {
            return fallback;
        }
    }

    /** 3725.4 → "1:02:05", 65 → "1:05" */
    function fmtTime( seconds ) {
        const s = Math.max( 0, Math.floor( Number( seconds ) || 0 ) );
        const h = Math.floor( s / 3600 );
        const m = Math.floor( ( s % 3600 ) / 60 );
        const sec = String( s % 60 ).padStart( 2, '0' );
        return h ? `${ h }:${ String( m ).padStart( 2, '0' ) }:${ sec }` : `${ m }:${ sec }`;
    }

    /** "2026-09-15" → Date at local midnight (avoids the UTC off-by-one). */
    function parseDate( ymd ) {
        const m = /^(\d{4})-(\d{2})-(\d{2})/.exec( ymd || '' );
        return m ? new Date( +m[ 1 ], +m[ 2 ] - 1, +m[ 3 ] ) : null;
    }

    function fmtDate( ymd, opts = { month: 'short', day: 'numeric', year: 'numeric' } ) {
        const d = parseDate( ymd );
        return d ? d.toLocaleDateString( 'en-US', opts ) : '';
    }

    /** CPS school/fiscal year runs July 1 – June 30: 2026-08-04 → "2026–27". */
    function schoolYear( ymd ) {
        const d = parseDate( ymd );
        if ( ! d ) return 'Undated';
        const start = d.getMonth() >= 6 ? d.getFullYear() : d.getFullYear() - 1;
        return `${ start }–${ String( start + 1 ).slice( 2 ) }`;
    }

    /**
     * Tiny element builder. Children may be strings (inserted as text,
     * never HTML), nodes, arrays, or falsy (skipped).
     */
    function el( tag, attrs = {}, ...children ) {
        const node = document.createElement( tag );
        Object.entries( attrs || {} ).forEach( ( [ k, v ] ) => {
            if ( v === false || v === null || v === undefined ) return;
            if ( k === 'class' ) node.className = v;
            else if ( k === 'dataset' ) Object.assign( node.dataset, v );
            else if ( k.startsWith( 'on' ) ) node.addEventListener( k.slice( 2 ), v );
            else node.setAttribute( k, v === true ? '' : v );
        } );
        append( node, children );
        return node;
    }

    function append( node, children ) {
        children.flat( Infinity ).forEach( ( c ) => {
            if ( c === null || c === undefined || c === false || c === '' ) return;
            node.append( c instanceof Node ? c : document.createTextNode( String( c ) ) );
        } );
        return node;
    }

    function escapeRegExp( s ) {
        return s.replace( /[.*+?^${}()|[\]\\]/g, '\\$&' );
    }

    /** Text with every case-insensitive occurrence of query wrapped in <mark>. */
    function highlight( text, query ) {
        const frag = document.createDocumentFragment();
        if ( ! query ) {
            frag.append( text );
            return frag;
        }
        const parts = String( text ).split( new RegExp( `(${ escapeRegExp( query ) })`, 'ig' ) );
        parts.forEach( ( part, i ) => {
            if ( ! part ) return;
            frag.append( i % 2 ? el( 'mark', {}, part ) : document.createTextNode( part ) );
        } );
        return frag;
    }

    /** Link to a meeting page at a moment, optionally carrying a search term. */
    function momentUrl( permalink, seconds, query ) {
        const url = new URL( permalink, config.homeUrl );
        if ( query ) url.searchParams.set( 'q', query );
        if ( seconds !== undefined && seconds !== null ) url.hash = `t=${ Math.floor( seconds ) }`;
        return url.toString();
    }

    /** What a vote was about: its agenda item's title, "N items: #…", or the motion text. */
    function voteLabel( v, max = 160 ) {
        const items = v.items || [];
        let label = String( v.motion_text || v.raw_context || 'Vote' );
        label = label.charAt( 0 ).toUpperCase() + label.slice( 1 );
        if ( items.length === 1 && items[ 0 ].title ) {
            label = `${ items[ 0 ].docket ? `#${ items[ 0 ].docket } ` : '' }${ items[ 0 ].title }`;
        } else if ( items.length > 1 ) {
            label = `${ items.length } items: #${ items.map( ( i ) => i.docket ).join( ', #' ) }`;
        }
        return label.length > max ? `${ label.slice( 0, max - 3 ) }…` : label;
    }

    /** "5–2" (or '' when the minutes recorded no tally) */
    function tallyText( v ) {
        return v.vote_for === null || v.vote_for === undefined ? '' : `${ v.vote_for }–${ v.vote_against }`;
    }

    function status( container, message, isError = false ) {
        container.replaceChildren( el( 'p', { class: isError ? 'status status--error' : 'status' }, message ) );
    }

    function debounce( fn, ms = 200 ) {
        let t;
        return ( ...args ) => {
            clearTimeout( t );
            t = setTimeout( () => fn( ...args ), ms );
        };
    }

    window.CR = {
        config, api, allMeetings, parseJson, fmtTime, parseDate, fmtDate, schoolYear,
        el, append, escapeRegExp, highlight, momentUrl, status, debounce, voteLabel, tallyText,
    };
} )();
