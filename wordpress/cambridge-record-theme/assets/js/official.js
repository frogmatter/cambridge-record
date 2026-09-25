/**
 * One official's voting record.
 * Source: GET /wp-json/cambridge-record/v1/officials/{id}
 */
( function () {
    'use strict';

    const { api, el, fmtDate, fmtTime, status, debounce, voteLabel, tallyText } = window.CR;

    const root = document.getElementById( 'record' );
    if ( ! root ) return;

    const listEl      = document.getElementById( 'record-list' );
    const summaryEl   = document.getElementById( 'record-summary' );
    const dissentsEl  = document.getElementById( 'only-dissents' );
    const proceduralEl = document.getElementById( 'show-procedural' );
    const filterEl    = document.getElementById( 'record-filter' );

    let votes = [];

    const VOTE_LABELS = { YEA: 'Yea', NAY: 'Nay', ABSENT: 'Absent', PRESENT: 'Present', ABSTAIN: 'Abstain', RECUSED: 'Recused' };

    function voteRow( v ) {
        return el( 'li', { class: `record-row${ v.dissent ? ' is-dissent' : '' }` },
            el( 'span', { class: `cast cast--${ v.member_vote.toLowerCase() }` }, VOTE_LABELS[ v.member_vote ] || v.member_vote ),
            el( 'div', { class: 'record-row__body' },
                el( 'a', { href: v.moment_url, class: 'record-row__title' }, voteLabel( v ) ),
                el( 'div', { class: 'vote-meta' },
                    el( 'span', { class: v.passed === false ? 'tag tag--failed' : 'tag tag--vote' }, v.result ),
                    tallyText( v ) ? el( 'span', {}, tallyText( v ) ) : null,
                    v.dissent ? el( 'span', { class: 'dissent-note' }, 'against the majority' ) : null
                )
            ),
            v.start_seconds !== null && v.start_seconds !== undefined
                ? el( 'a', { href: v.moment_url, class: 'record-row__time', 'aria-label': `Watch this vote at ${ fmtTime( v.start_seconds ) }` }, `▶ ${ fmtTime( v.start_seconds ) }` )
                : el( 'span' )
        );
    }

    function render() {
        const q = filterEl.value.trim().toLowerCase();
        const shown = votes.filter( ( v ) =>
            ( proceduralEl.checked || ! v.procedural ) &&
            ( ! dissentsEl.checked || v.dissent ) &&
            ( ! q || [ voteLabel( v, 1000 ), v.motion_text, v.meeting_title ].join( ' ' ).toLowerCase().includes( q ) )
        );

        if ( ! votes.length ) {
            status( listEl, 'No recorded votes yet. Votes come from the official minutes, which are posted a few weeks after each meeting.' );
            return;
        }
        if ( ! shown.length ) {
            status( listEl, 'No votes match these filters.' );
            return;
        }

        const byMeeting = new Map();
        shown.forEach( ( v ) => {
            if ( ! byMeeting.has( v.meeting_id ) ) byMeeting.set( v.meeting_id, [] );
            byMeeting.get( v.meeting_id ).push( v );
        } );

        listEl.replaceChildren( ...[ ...byMeeting.values() ].map( ( group ) =>
            el( 'section', { class: 'result-group' },
                el( 'div', { class: 'result-group__head' },
                    el( 'h3', {}, el( 'a', { href: group[ 0 ].meeting_url }, group[ 0 ].meeting_title ) ),
                    el( 'span', { class: 'muted' }, fmtDate( group[ 0 ].meeting_date, { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' } ) )
                ),
                el( 'ol', { class: 'record-list' }, group.map( voteRow ) )
            )
        ) );
    }

    async function load() {
        try {
            const data = await api( `cambridge-record/v1/officials/${ root.dataset.id }` );
            votes = data.votes || [];
            const s = data.summary || {};
            if ( s.votes ) {
                summaryEl.textContent = [
                    `${ s.votes } roll-call votes in ${ s.meetings } meeting${ s.meetings === 1 ? '' : 's' }`,
                    `${ s.yea } yea`, `${ s.nay } nay`,
                    s.absent ? `${ s.absent } absent` : null,
                    `${ s.dissents } against the majority`,
                ].filter( Boolean ).join( ' · ' );
            }
            render();
        } catch ( e ) {
            status( listEl, 'Couldn’t load the voting record. Please refresh the page.', true );
        }
    }

    [ dissentsEl, proceduralEl ].forEach( ( x ) => x.addEventListener( 'change', render ) );
    filterEl.addEventListener( 'input', debounce( render, 150 ) );
    load();
} )();
