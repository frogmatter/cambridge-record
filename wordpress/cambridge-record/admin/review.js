/**
 * Meetings → Review times.
 * Lists votes/agenda items the pipeline placed with low confidence (or not
 * at all), plays the meeting at the best guess, follows the transcript
 * around the playhead, and saves a person's decision.
 *
 * Talks to the Cablecast player the same way the theme does: ?seek=N,
 * postMessage {type:'player-cue'} to jump, 'timeupdate' messages back.
 */
( function () {
    'use strict';

    const cfg = window.CR_REVIEW;
    const $ = ( id ) => document.getElementById( id );

    const rowsEl = $( 'cr-rows' ), meetingEl = $( 'cr-meeting' ), allEl = $( 'cr-all' );
    const panel = $( 'cr-panel' ), player = $( 'cr-player' ), nowEl = $( 'cr-now' );
    const titleEl = $( 'cr-item-title' ), detailEl = $( 'cr-item-detail' ), msgEl = $( 'cr-message' );
    const timeEl = $( 'cr-time' ), transcriptEl = $( 'cr-transcript' ), progressEl = $( 'cr-progress' );

    let meetings = new Map();   // id → meeting
    let items = [];
    let current = null;         // selected item
    let playerMeeting = null, playerReady = false, playerOrigin = null;
    let currentTime = null;
    const segmentCache = new Map();   // meeting id → segments

    // ── Helpers ───────────────────────────────────────

    async function api( url, options = {} ) {
        const res = await fetch( url, {
            ...options,
            headers: { 'X-WP-Nonce': cfg.nonce, 'Content-Type': 'application/json', ...( options.headers || {} ) },
            credentials: 'same-origin',
        } );
        const body = await res.json();
        if ( ! res.ok ) throw new Error( body.message || `Request failed (${ res.status })` );
        return body;
    }

    function fmt( s ) {
        if ( s === null || s === undefined ) return '—';
        s = Math.max( 0, Math.floor( s ) );
        return `${ Math.floor( s / 3600 ) }:${ String( Math.floor( s % 3600 / 60 ) ).padStart( 2, '0' ) }:${ String( s % 60 ).padStart( 2, '0' ) }`;
    }

    function parseTime( text ) {
        const parts = String( text ).trim().split( ':' ).map( Number );
        if ( ! parts.length || parts.some( ( n ) => ! Number.isFinite( n ) || n < 0 ) ) return null;
        return parts.reduce( ( acc, n ) => acc * 60 + n, 0 );
    }

    function el( tag, attrs = {}, ...children ) {
        const node = document.createElement( tag );
        Object.entries( attrs ).forEach( ( [ k, v ] ) => {
            if ( v === null || v === undefined || v === false ) return;
            if ( k === 'class' ) node.className = v;
            else if ( k.startsWith( 'on' ) ) node.addEventListener( k.slice( 2 ), v );
            else node.setAttribute( k, v );
        } );
        children.flat().forEach( ( c ) => c !== null && c !== undefined && c !== false && node.append( c instanceof Node ? c : String( c ) ) );
        return node;
    }

    function statusLabel( item ) {
        if ( item.decision ) {
            return { confirmed: '✓ Confirmed', corrected: '✓ Time set', cleared: '✓ Not in video' }[ item.decision.status ];
        }
        if ( item.start_seconds === null ) return 'Not placed';
        return item.match_score !== null && item.match_score !== undefined ? `Low confidence (${ Number( item.match_score ).toFixed( 2 ) })` : 'Check';
    }

    // ── Queue ─────────────────────────────────────────

    async function loadQueue() {
        const id = meetingEl.value;
        const url = new URL( cfg.restRoot );
        if ( id ) url.searchParams.set( 'meeting', id );
        if ( id && allEl.checked ) url.searchParams.set( 'all', '1' );
        const data = await api( url );

        meetings = new Map( data.meetings.map( ( m ) => [ m.id, m ] ) );
        const selected = meetingEl.value;
        meetingEl.replaceChildren(
            el( 'option', { value: '' }, 'All meetings that need review' ),
            ...data.meetings.filter( ( m ) => m.total ).map( ( m ) =>
                el( 'option', { value: m.id, selected: String( m.id ) === selected ? 'selected' : null },
                    `${ m.date } — ${ m.title }${ m.needs ? ` (${ m.needs } to review)` : ' ✓' }${ m.status !== 'publish' ? ' [draft]' : '' }` ) )
        );
        const needs = data.meetings.reduce( ( s, m ) => s + m.needs, 0 );
        const reviewed = data.meetings.reduce( ( s, m ) => s + m.reviewed, 0 );
        progressEl.textContent = `${ needs } left to review · ${ reviewed } reviewed`;

        items = data.items;
        renderRows();
    }

    function renderRows() {
        if ( ! items.length ) {
            rowsEl.replaceChildren( el( 'tr', {}, el( 'td', { colspan: 4 }, 'Nothing to review here.' ) ) );
            return;
        }
        rowsEl.replaceChildren( ...items.map( ( item ) => {
            const m = meetings.get( item.meeting_id ) || {};
            const tr = el( 'tr', {
                class: `cr-row${ item === current ? ' is-current' : '' }${ item.decision ? ' is-done' : '' }`,
                tabindex: 0,
                onclick: () => select( item ),
                onkeydown: ( e ) => e.key === 'Enter' && select( item ),
            },
                el( 'td', { class: 'cr-row__meeting' }, m.date || '', el( 'br' ), el( 'span', { class: 'description' }, m.title || '' ) ),
                el( 'td', {}, el( 'strong', {}, item.label ),
                    el( 'div', { class: 'description' }, item.kind === 'agenda' ? 'Agenda item' : [ item.result, item.tally ].filter( Boolean ).join( ' · ' ) ) ),
                el( 'td', { class: 'cr-row__time' }, fmt( item.start_seconds ) ),
                el( 'td', {}, statusLabel( item ) )
            );
            item._row = tr;
            return tr;
        } ) );
    }

    // ── Player ────────────────────────────────────────

    function seekUrl( embed, s ) {
        const url = new URL( embed );
        url.searchParams.delete( 't' );
        url.searchParams.set( 'seek', Math.floor( s || 0 ) );
        return url.toString();
    }

    function seek( s ) {
        const m = meetings.get( current.meeting_id );
        if ( playerMeeting === m.id && playerReady ) {
            player.contentWindow.postMessage( { type: 'player-cue', value: Math.floor( s ) }, playerOrigin );
        } else {
            playerMeeting = m.id;
            playerReady = false;
            playerOrigin = new URL( m.embed_url ).origin;
            player.src = seekUrl( m.embed_url, s );
        }
        currentTime = Math.floor( s );
        updateNow();
        renderTranscript();
    }

    window.addEventListener( 'message', ( e ) => {
        if ( e.source !== player.contentWindow || e.origin !== playerOrigin ) return;
        const d = e.data || {};
        if ( d.message === 'ready' || d.message === 'playing' ) playerReady = true;
        if ( d.message === 'timeupdate' && Number.isFinite( Number( d.value ) ) ) {
            playerReady = true;
            const t = Math.floor( Number( d.value ) );
            if ( t !== currentTime ) {
                currentTime = t;
                updateNow();
                renderTranscript();
            }
        }
    } );

    function updateNow() {
        nowEl.textContent = fmt( currentTime );
        $( 'cr-use-now' ).textContent = `Use current time (${ fmt( currentTime ) })`;
    }

    // ── Transcript around the playhead ────────────────

    async function segmentsFor( meetingId ) {
        if ( ! segmentCache.has( meetingId ) ) {
            const data = await api( `${ cfg.wpRoot }${ meetingId }?context=edit&_fields=meta.segments_json` );
            segmentCache.set( meetingId, JSON.parse( data.meta.segments_json || '[]' ) );
        }
        return segmentCache.get( meetingId );
    }

    let renderedWindow = null;
    function renderTranscript() {
        const segs = current && segmentCache.get( current.meeting_id );
        if ( ! segs || currentTime === null ) return;
        const from = currentTime - 45, to = currentTime + 60;
        const key = `${ current.meeting_id }:${ Math.floor( from / 5 ) }`;
        if ( renderedWindow === key ) {
            highlightNow();
            return;
        }
        renderedWindow = key;
        const near = segs.filter( ( s ) => s.start_seconds >= from && s.start_seconds <= to );
        if ( ! near.length ) {
            transcriptEl.replaceChildren( el( 'p', { class: 'description' }, `No captions near ${ fmt( currentTime ) }.` ) );
            return;
        }
        const rollWords = /\b(roll call|call the roll|yes|yea|no|nay|absent|present|motion|second(ed)?|affirmative)\b/gi;
        transcriptEl.replaceChildren( ...near.map( ( s ) => {
            const p = el( 'p', { class: 'cr-line', 'data-t': s.start_seconds, onclick: () => seek( s.start_seconds ) },
                el( 'span', { class: 'cr-line__t' }, fmt( s.start_seconds ) ), ' ' );
            // Emphasise the words that signal a vote, to make roll calls easy to spot
            let last = 0;
            const text = s.text;
            for ( const m of text.matchAll( rollWords ) ) {
                p.append( text.slice( last, m.index ), el( 'mark', {}, m[ 0 ] ) );
                last = m.index + m[ 0 ].length;
            }
            p.append( text.slice( last ) );
            return p;
        } ) );
        highlightNow();
    }

    function highlightNow() {
        let active = null;
        transcriptEl.querySelectorAll( '.cr-line' ).forEach( ( line ) => {
            line.classList.remove( 'is-now' );
            if ( Number( line.dataset.t ) <= currentTime + 0.999 ) active = line;
        } );
        if ( active ) active.classList.add( 'is-now' );
    }

    // ── Selecting and deciding ────────────────────────

    async function select( item, { keepMessage = false } = {} ) {
        current = item;
        renderRows();
        panel.hidden = false;
        if ( ! keepMessage ) msgEl.textContent = '';
        titleEl.textContent = item.label;

        const parts = [];
        if ( item.kind === 'vote' ) {
            parts.push( `Minutes: ${ item.motion_text }${ item.tally ? ` (${ item.tally })` : '' }.` );
            if ( item.start_seconds === null ) {
                parts.push( item.after_seconds !== null && item.after_seconds !== undefined
                    ? `Not found in the captions. It should be after the previous vote (${ fmt( item.after_seconds ) })${ item.before_seconds ? ` and before the next (${ fmt( item.before_seconds ) })` : '' }.`
                    : 'Not found in the captions.' );
            } else {
                parts.push( `Placed at ${ fmt( item.start_seconds ) } by ${ item.match_method || 'matching' }, confidence ${ Number( item.match_score ).toFixed( 2 ) }.` );
            }
        } else {
            parts.push( item.start_seconds === null ? 'Its docket number wasn’t found in the captions.' : `Placed at ${ fmt( item.start_seconds ) }.` );
        }
        detailEl.textContent = parts.join( ' ' );

        $( 'cr-confirm' ).disabled = item.start_seconds === null;
        $( 'cr-reset' ).hidden = ! item.decision;
        timeEl.value = item.start_seconds !== null ? fmt( item.start_seconds ) : '';

        renderedWindow = null;
        transcriptEl.replaceChildren( el( 'p', { class: 'description' }, 'Loading transcript…' ) );
        await segmentsFor( item.meeting_id );
        seek( item.start_seconds ?? item.after_seconds ?? 0 );
    }

    async function decide( action, seconds ) {
        if ( ! current ) return;
        try {
            const updated = await api( cfg.restRoot, {
                method: 'POST',
                body: JSON.stringify( { meeting_id: current.meeting_id, kind: current.kind, key: current.key, action, start_seconds: seconds } ),
            } );
            Object.assign( current, updated );
            msgEl.textContent = { confirm: `Confirmed: ${ current.label }.`, set: `Saved ${ fmt( seconds ) } for ${ current.label }.`, clear: 'Marked as not in the video.', reset: 'Decision undone — back to what the pipeline found.' }[ action ];
            const next = items.find( ( i ) => ! i.decision && i !== current );
            await loadQueue();
            // Keep the list stable: re-find the item we were on, then move to the next undecided one
            if ( action !== 'reset' && next ) {
                const again = items.find( ( i ) => i.key === next.key && i.meeting_id === next.meeting_id );
                if ( again ) setTimeout( () => select( again, { keepMessage: true } ), 600 );
            }
        } catch ( e ) {
            msgEl.textContent = `Couldn’t save: ${ e.message }`;
        }
    }

    $( 'cr-use-now' ).addEventListener( 'click', () => currentTime !== null && decide( 'set', currentTime ) );
    $( 'cr-confirm' ).addEventListener( 'click', () => decide( 'confirm' ) );
    $( 'cr-set' ).addEventListener( 'click', () => {
        const s = parseTime( timeEl.value );
        if ( s === null ) { msgEl.textContent = 'Enter a time like 1:02:05.'; return; }
        decide( 'set', s );
    } );
    timeEl.addEventListener( 'keydown', ( e ) => e.key === 'Enter' && $( 'cr-set' ).click() );
    $( 'cr-clear' ).addEventListener( 'click', () => decide( 'clear' ) );
    $( 'cr-reset' ).addEventListener( 'click', () => decide( 'reset' ) );
    meetingEl.addEventListener( 'change', () => { allEl.disabled = ! meetingEl.value; loadQueue(); } );
    allEl.addEventListener( 'change', loadQueue );
    allEl.disabled = true;

    loadQueue().catch( ( e ) => rowsEl.replaceChildren( el( 'tr', {}, el( 'td', { colspan: 4 }, `Couldn’t load: ${ e.message }` ) ) ) );
} )();
