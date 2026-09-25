/**
 * Officials list — /officials/
 * Source: GET /wp-json/cambridge-record/v1/officials
 */
( function () {
    'use strict';

    const { api, el, status } = window.CR;

    const listEl = document.getElementById( 'officials' );
    if ( ! listEl ) return;

    function summaryLine( s ) {
        if ( ! s || ! s.votes ) return 'No recorded votes yet';
        const parts = [ `${ s.votes } roll-call vote${ s.votes === 1 ? '' : 's' } in ${ s.meetings } meeting${ s.meetings === 1 ? '' : 's' }` ];
        if ( s.dissents ) parts.push( `${ s.dissents } against the majority` );
        if ( s.absent ) parts.push( `absent for ${ s.absent }` );
        return parts.join( ' · ' );
    }

    function row( o ) {
        const leads = ( o.subcommittees || [] ).filter( ( sc ) => sc.role && sc.role !== 'Member' );
        return el( 'li', { class: 'official-row' },
            el( 'div', { class: 'official-row__title' }, o.title ),
            el( 'h3', { class: 'official-row__name' }, el( 'a', { href: o.permalink }, o.name ) ),
            el( 'div', { class: 'official-row__meta' },
                o.is_voting ? summaryLine( o.summary ) : 'Non-voting student member',
                leads.length ? el( 'span', { class: 'muted' }, ` · ${ leads.map( ( sc ) => `${ sc.role }, ${ sc.name }` ).join( '; ' ) }` ) : null
            )
        );
    }

    async function load() {
        try {
            const { officials = [] } = await api( 'cambridge-record/v1/officials' );
            if ( ! officials.length ) {
                status( listEl, 'No officials have been published yet.' );
                return;
            }
            const voting = officials.filter( ( o ) => o.is_voting );
            const other = officials.filter( ( o ) => ! o.is_voting );
            listEl.replaceChildren(
                el( 'ul', { class: 'meeting-list official-list' }, voting.map( row ) ),
                other.length ? el( 'h2', { class: 'official-group' }, 'Student members' ) : null,
                other.length ? el( 'ul', { class: 'meeting-list official-list' }, other.map( row ) ) : null,
                el( 'p', { class: 'search-note' }, 'Votes come from the official minutes, which are posted a few weeks after each meeting. Only roll-call votes record how each member voted.' )
            );
        } catch ( e ) {
            status( listEl, 'Couldn’t load officials. Please refresh the page.', true );
        }
    }

    load();
} )();
